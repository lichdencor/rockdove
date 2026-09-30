import asyncio
import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

import config_store
import token_store
from config import get_settings
from rs.decoder import decode_transfer
from rs.encoder import encode_file
from rs.models import TransferStatus
from rs.transport import QUICTransport, UDPTransport, get_transport, set_transport
from server_client import server_client
from metrics.otel import get_meter
from storage.db import insert_transfer, list_history
from storage.store import FileStorage
from transfers.models import HistoryEntry, IncomingConnection, ReceiveRequest, SendRequest, TransferResult

router = APIRouter()

_transfers: dict[str, dict] = {}
_transport_requests: dict[str, dict] = {}


def _check_incoming_policy(sender_peer_id: str | None) -> None:
    """Raise HTTP 403 if the effective incoming policy rejects this sender.

    config_store values take precedence (server admin can push overrides via the
    /peers/{id}/incoming-policy endpoint, which _apply_server_incoming_policy
    writes into config_store on startup).
    """
    settings = get_settings()
    policy: str = config_store.get("incoming_policy", settings.INCOMING_POLICY)

    if policy == "allow_all":
        return
    if policy == "deny_all":
        raise HTTPException(403, "Incoming transfers are disabled on this peer")

    if policy == "allow_list":
        raw = config_store.get("incoming_allowed_peers", settings.INCOMING_ALLOWED_PEERS)
        allowed = {p.strip() for p in raw.split(",") if p.strip()}
        if not sender_peer_id or sender_peer_id not in allowed:
            raise HTTPException(403, f"Sender '{sender_peer_id}' is not in the allow list")

    if policy == "deny_list":
        raw = config_store.get("incoming_denied_peers", settings.INCOMING_DENIED_PEERS)
        denied = {p.strip() for p in raw.split(",") if p.strip()}
        if sender_peer_id and sender_peer_id in denied:
            raise HTTPException(403, f"Sender '{sender_peer_id}' is blocked on this peer")


async def _relay_candidates(target: str) -> list[str]:
    """Online peers (other than self and target) that could act as relays."""
    settings = get_settings()
    try:
        peers = await server_client.get_peers()
    except Exception:
        return []
    return [
        p["peer_id"]
        for p in peers
        if p.get("peer_id")
        and p.get("online")
        and p["peer_id"] != settings.PEER_ID
        and p["peer_id"] != target
    ]


@router.post("/send", response_model=TransferResult)
async def send_file(req: SendRequest) -> TransferResult:
    get_meter().create_counter("rs_transfers_total").add(1, {"direction": "sent"})
    settings = get_settings()
    storage = FileStorage(settings.STORAGE_PATH)

    meta = storage.get_meta(req.file_id)
    if not meta:
        raise HTTPException(404, "File not found")
    file_bytes = storage.get_bytes(req.file_id)
    if file_bytes is None:
        raise HTTPException(404, "File bytes not found")

    redundancy_level = req.redundancy_level
    effective_quality: str | None = None
    effective_profile: str | None = None
    should_relay = False
    relay_peer_id: str | None = None
    route_source: str | None = None
    route_confidence: float | None = None

    if redundancy_level is None:
        # Jev-based transit decision: one call returns the redundancy gradient
        # (combining both endpoints) AND whether to jump through a relay.
        relays = await _relay_candidates(req.target_peer_id)
        route = await server_client.get_transit_decision(
            settings.PEER_ID, req.target_peer_id, relays=relays
        )
        redundancy_level = route["redundancy_level"]
        effective_quality = route.get("quality")
        effective_profile = route.get("profile_name")
        should_relay = bool(route.get("should_relay"))
        relay_peer_id = route.get("relay_peer_id")
        route_source = route.get("source_name")
        route_confidence = route.get("confidence")

    # Resolve the transport endpoint. If Jev chose a relay and it differs from
    # the direct target, we send to the relay address (P2.2 relay forwarding on
    # the receiver side is the remaining piece; the endpoint/decision plumbing
    # is wired here).
    try:
        peer = await server_client.get_peer(req.target_peer_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    peer_transport = peer.get("transport", "udp")
    requested_transport = req.transport or peer_transport
    if requested_transport != peer_transport:
        raise HTTPException(
            400,
            f"Transport mismatch: peer is registered as '{peer_transport}', requested '{requested_transport}'",
        )

    target_api_url = peer["api_url"]
    target_udp_host = peer["udp_host"]
    target_udp_port = peer["udp_port"]

    packets, transfer_id, n, k, chunk_size = encode_file(file_bytes, redundancy_level)

    effective_pid = token_store.get_peer_id() or settings.PEER_ID

    receive_payload = {
        "transfer_id": transfer_id,
        "checksum": meta["sha256"],
        "file_size": len(file_bytes),
        "n": n, "k": k, "chunk_size": chunk_size,
        "filename": meta.get("filename", ""),
        "sender_peer_id": effective_pid,
    }

    relay_info: dict | None = None
    relay_tag: str | None = None

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            r = await client.post(
                f"{target_api_url}/transfer/receive",
                json=receive_payload,
            )
            if r.status_code not in (200, 202):
                raise HTTPException(502, f"Peer rejected transfer: {r.text}")
        except httpx.RequestError:
            # Direct path failed — attempt relay fallback
            try:
                relay_info = await server_client.get_relay_for_peer(req.target_peer_id)
            except ValueError as relay_err:
                raise HTTPException(502, f"Cannot reach peer directly and no relay available: {relay_err}")
            relay_tag = f"rly-{secrets.token_hex(4)}"
            relay_api_url = relay_info["api_url"]
            relay_payload = {**receive_payload, "relay_to": req.target_peer_id, "relay_tag": relay_tag}
            try:
                r = await client.post(f"{relay_api_url}/transfer/receive", json=relay_payload)
                if r.status_code not in (200, 202):
                    raise HTTPException(502, f"Relay rejected transfer: {r.text}")
            except httpx.RequestError as relay_exc:
                raise HTTPException(502, f"Cannot reach relay peer: {relay_exc}")
            # Override send target to relay
            target_api_url = relay_api_url
            target_udp_host = relay_info["udp_host"]
            target_udp_port = relay_info["udp_port"]

    t_send = time.monotonic()
    await get_transport().send(packets, target_udp_host, target_udp_port)
    get_meter().create_counter("rs_packets_sent_total").add(len(packets))

    result = TransferResult(
        transfer_id=transfer_id,
        status=TransferStatus.failed,
        reason="timeout_waiting_for_peer_result",
    )
    async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
        for _ in range(70):
            await asyncio.sleep(0.5)
            try:
                r = await client.get(f"{target_api_url}/transfer/{transfer_id}/status")
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") not in ("pending", None):
                        result = TransferResult(**data)
                        break
            except httpx.RequestError:
                pass

    elapsed_ms = (time.monotonic() - t_send) * 1000.0
    loss_rate = (
        result.recovered_blocks / result.total_blocks
        if result.total_blocks > 0
        else 0.0
    )
    asyncio.create_task(
        server_client.report_metrics(
            settings.PEER_ID,
            rtt_ms=elapsed_ms,
            jitter_ms=0.0,
            loss_rate=loss_rate,
        )
    )
    asyncio.create_task(
        insert_transfer(
            transfer_id=transfer_id,
            direction="sent",
            peer_id=req.target_peer_id,
            filename=meta.get("filename"),
            bytes_=len(file_bytes),
            status=str(result.status.value if hasattr(result.status, "value") else result.status),
            redundancy=redundancy_level,
            recovered_blocks=result.recovered_blocks,
            total_blocks=result.total_blocks,
            quality=effective_quality,
            profile_name=effective_profile,
        )
    )

    base = result.model_dump(exclude={
        "effective_redundancy", "quality", "profile_name",
        "relay_tag", "relay_target", "via_relay",
        "should_relay", "relay_peer_id", "route_source", "route_confidence",
    })
    return TransferResult(
        **base,
        effective_redundancy=redundancy_level,
        quality=effective_quality,
        profile_name=effective_profile,
        should_relay=should_relay,
        relay_peer_id=relay_peer_id,
        route_source=route_source,
        route_confidence=route_confidence,
        relay_tag=relay_tag,
        relay_target=req.target_peer_id if relay_info else None,
        via_relay=relay_info is not None,
    )


@router.post("/receive", status_code=202)
async def receive_transfer(req: ReceiveRequest, background_tasks: BackgroundTasks) -> dict:
    settings = get_settings()
    if req.relay_to and not settings.RELAY_CAPABLE:
        raise HTTPException(403, "This agent is not configured as a relay")

    # Enforce local incoming-transfer policy (skip for relay: relay ACL handled separately)
    if not req.relay_to:
        _check_incoming_policy(req.sender_peer_id)

    _transfers[req.transfer_id] = {"status": "pending"}
    if req.relay_to:
        background_tasks.add_task(_process_relay, req)
    else:
        background_tasks.add_task(_process_incoming, req)
    return {"transfer_id": req.transfer_id, "status": "pending"}


async def _process_incoming(req: ReceiveRequest) -> None:
    get_meter().create_counter("rs_transfers_total").add(1, {"direction": "received"})
    settings = get_settings()
    transport = get_transport()

    # If QUIC: wait for operator to approve the incoming cert-authenticated connection
    # before decoding.  Auto-approves on timeout so the transfer never stalls.
    if isinstance(transport, QUICTransport):
        approved = await transport.wait_for_approval(req.transfer_id, timeout=30.0)
        if not approved:
            transport.clear_buffer(req.transfer_id)
            _transfers[req.transfer_id] = {
                "transfer_id": req.transfer_id,
                "status": TransferStatus.failed,
                "recovered_blocks": 0,
                "total_blocks": 0,
                "file_id": None,
                "reason": "rejected_by_operator",
            }
            return

    packets = await transport.collect(req.transfer_id, timeout=req.timeout)
    result = decode_transfer(packets, req.checksum)
    
    if result.recovered_blocks > 0:
        get_meter().create_counter("rs_packets_recovered_total").add(result.recovered_blocks)

    file_id = None
    if result.status != TransferStatus.failed and result.file_bytes:
        storage = FileStorage(settings.STORAGE_PATH)
        saved = storage.save(result.file_bytes, req.filename or f"transfer_{req.transfer_id}")
        file_id = saved["file_id"]

    _transfers[req.transfer_id] = {
        "transfer_id": req.transfer_id,
        "status": result.status,
        "recovered_blocks": result.recovered_blocks,
        "total_blocks": result.total_blocks,
        "file_id": file_id,
        "reason": result.reason,
    }
    asyncio.create_task(
        insert_transfer(
            transfer_id=req.transfer_id,
            direction="received",
            peer_id=None,
            filename=f"transfer_{req.transfer_id}",
            bytes_=req.file_size,
            status=str(result.status.value if hasattr(result.status, "value") else result.status),
            recovered_blocks=result.recovered_blocks,
            total_blocks=result.total_blocks,
        )
    )


async def _process_relay(req: ReceiveRequest) -> None:
    """
    Relay mode: collect RS packets from sender, forward to the final target,
    then destroy the buffer. Never writes to STORAGE_PATH (ephemeral by design).

    Supports two target resolution strategies:
      1. Static routes (RELAY_STATIC_ROUTES env) — no server TCP needed (gateway mode)
      2. Server lookup — standard peer discovery for normal relay use cases
    """
    settings = get_settings()
    transport = get_transport()
    target_id = req.relay_to  # guaranteed non-None by caller

    # Access control for restricted relays
    relay_tags = [t.strip() for t in settings.RELAY_TAGS.split(",") if t.strip()]
    if "restricted" in relay_tags and req.relay_tag:
        allowed_peers = {p.strip() for p in settings.RELAY_ALLOWED_PEERS.split(",") if p.strip()}
        # relay_tag encodes sender identity as "rly-{hex}" — we can't verify peer_id from UDP
        # so restricted mode relies on the relay_tag being kept secret between sender and relay.
        # Full identity verification requires QUIC + CERT_HELLO (future enhancement).
        pass

    # Collect packets in transport's in-memory buffer (never touches disk)
    packets = await transport.collect(req.transfer_id, timeout=req.timeout)

    if not packets:
        _transfers[req.transfer_id] = {
            "transfer_id": req.transfer_id,
            "status": TransferStatus.failed,
            "recovered_blocks": 0,
            "total_blocks": 0,
            "file_id": None,
            "reason": "relay_collect_timeout",
            "relay_tag": req.relay_tag,
            "relay_target": target_id,
            "via_relay": True,
        }
        return

    # Gateway access control — only checked when forwarding via a static route
    try:
        static_routes: dict = json.loads(settings.RELAY_STATIC_ROUTES)
    except Exception:
        static_routes = {}

    if target_id in static_routes and "gateway" in relay_tags:
        gateway_allowed = {p.strip() for p in settings.RELAY_GATEWAY_ALLOWED_PEERS.split(",") if p.strip()}
        if gateway_allowed and (not req.sender_peer_id or req.sender_peer_id not in gateway_allowed):
            _transfers[req.transfer_id] = {
                "transfer_id": req.transfer_id,
                "status": TransferStatus.failed,
                "recovered_blocks": 0,
                "total_blocks": 0,
                "file_id": None,
                "reason": f"gateway_access_denied: sender '{req.sender_peer_id}' not in allowed list",
                "relay_tag": req.relay_tag,
                "relay_target": target_id,
                "via_relay": True,
            }
            return

    # Resolve target address —————————————————————————————————————————————
    # Priority 1: static routing table (already loaded above)

    target_host: str | None = None
    target_port: int | None = None
    target_api_url: str | None = None

    if target_id in static_routes:
        route = static_routes[target_id]
        target_host = route["host"]
        target_port = int(route.get("port", 9001))
        api_port = int(route.get("api_port", 8000))
        target_api_url = f"http://{target_host}:{api_port}"
    else:
        # Priority 2: server peer registry lookup
        try:
            peer = await server_client.get_peer(target_id)
            target_host = peer["udp_host"]
            target_port = int(peer["udp_port"])
            target_api_url = peer["api_url"]
        except Exception as e:
            _transfers[req.transfer_id] = {
                "transfer_id": req.transfer_id,
                "status": TransferStatus.failed,
                "recovered_blocks": 0,
                "total_blocks": len(packets),
                "file_id": None,
                "reason": f"relay_target_not_found: {e}",
                "relay_tag": req.relay_tag,
                "relay_target": target_id,
                "via_relay": True,
            }
            return

    # Signal target to expect incoming transfer —————————————————————————————
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            r = await client.post(
                f"{target_api_url}/transfer/receive",
                json={
                    "transfer_id": req.transfer_id,
                    "checksum": req.checksum,
                    "file_size": req.file_size,
                    "n": req.n,
                    "k": req.k,
                    "chunk_size": req.chunk_size,
                    "filename": req.filename,
                    "sender_peer_id": req.sender_peer_id,
                    # No relay_to — this is the final hop
                },
            )
            if r.status_code not in (200, 202):
                raise RuntimeError(f"target rejected: {r.text}")
        except Exception as e:
            _transfers[req.transfer_id] = {
                "transfer_id": req.transfer_id,
                "status": TransferStatus.failed,
                "recovered_blocks": 0,
                "total_blocks": len(packets),
                "file_id": None,
                "reason": f"relay_notify_target_failed: {e}",
                "relay_tag": req.relay_tag,
                "relay_target": target_id,
                "via_relay": True,
            }
            return

    # Forward packets to target (buffer is consumed and will be GC'd after this) ——
    await transport.send(packets, target_host, target_port)

    # Poll target for final delivery status ————————————————————————————————
    final_status = "unknown"
    async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
        for _ in range(70):
            await asyncio.sleep(0.5)
            try:
                r = await client.get(f"{target_api_url}/transfer/{req.transfer_id}/status")
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") not in ("pending", None):
                        final_status = data.get("status", "unknown")
                        break
            except httpx.RequestError:
                pass

    _transfers[req.transfer_id] = {
        "transfer_id": req.transfer_id,
        "status": TransferStatus.relayed,
        "recovered_blocks": 0,
        "total_blocks": len(packets),
        "file_id": None,
        "reason": f"delivered:{final_status}",
        "relay_tag": req.relay_tag,
        "relay_target": target_id,
        "via_relay": True,
    }


@router.get("/{transfer_id}/status", response_model=TransferResult)
async def get_status(transfer_id: str) -> TransferResult:
    if transfer_id not in _transfers:
        raise HTTPException(404, "Transfer not found")
    data = _transfers[transfer_id]
    if data.get("status") == "pending":
        return TransferResult(transfer_id=transfer_id, status=TransferStatus.pending)
    return TransferResult(**data)


@router.get("/history", response_model=list[HistoryEntry])
async def get_history(limit: int = 50) -> list[HistoryEntry]:
    rows = await list_history(limit=limit)
    return [HistoryEntry(**r) for r in rows]


@router.get("/route/{target_peer_id}")
async def jev_route(
    target_peer_id: str,
    relay: list[str] = Query(default=[], description="Explicit relay candidates"),
) -> dict:
    """Query the best route to `target_peer_id` as decided by Jev.

    Works in headless/TTY mode: call this on a running agent's local API to see
    the redundancy gradient + relay decision Jev recommends for source→target.
    Returns the raw server decision plus the candidate relays considered.
    """
    settings = get_settings()
    relays = relay or await _relay_candidates(target_peer_id)
    route = await server_client.get_transit_decision(
        settings.PEER_ID, target_peer_id, relays=relays
    )
    return {
        "source": settings.PEER_ID,
        "target": target_peer_id,
        "relay_candidates": relays,
        "decision": route,
    }


@router.get("/", response_model=list[TransferResult])
async def list_transfers() -> list[TransferResult]:
    return [TransferResult(**v) for v in _transfers.values()]


# ── Transport negotiation ─────────────────────────────────────────────────────

class TransportRequestBody(BaseModel):
    sender_peer_id: str
    requested_transport: Literal["udp", "quic"]


async def _switch_transport(mode: str) -> None:
    """Stop the current transport, start a new one, update token_store, re-register."""
    import config_store
    settings = get_settings()
    udp_host = config_store.get("udp_host", settings.UDP_HOST)
    udp_port = config_store.get("udp_port", settings.UDP_PORT)

    old_transport = get_transport()
    new_transport = QUICTransport() if mode == "quic" else UDPTransport()

    old_transport.stop()
    set_transport(new_transport)
    await new_transport.start(udp_host, udp_port)

    token_store.set_transport_mode(mode)

    pid = token_store.get_peer_id() or config_store.get("peer_id", settings.PEER_ID)
    try:
        advertise = config_store.get("udp_advertise_host", "") or settings.udp_advertise_host
        result = await server_client.register(
            peer_id=pid,
            api_url=config_store.get("agent_api_url", "") or settings.AGENT_API_URL,
            udp_host=advertise,
            udp_port=udp_port,
            transport=mode,
        )
        token_store.set_peer_id(result.get("peer_id", pid))
    except Exception:
        pass


@router.post("/transport-request")
async def receive_transport_request(body: TransportRequestBody) -> dict:
    """Called by a remote peer's sender to ask us to switch transport."""
    req_id = str(uuid.uuid4())
    _transport_requests[req_id] = {
        "request_id": req_id,
        "sender_peer_id": body.sender_peer_id,
        "requested_transport": body.requested_transport,
        "arrived_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    return {"request_id": req_id}


@router.get("/transport-requests")
async def list_transport_requests() -> list[dict]:
    """Return all pending transport-switch requests."""
    return list(_transport_requests.values())


@router.post("/transport-requests/{req_id}/accept")
async def accept_transport_request(req_id: str) -> dict:
    """Accept a transport-switch request, switch transport, and re-register."""
    req = _transport_requests.get(req_id)
    if req is None:
        raise HTTPException(404, "Transport request not found")

    mode = req["requested_transport"]

    try:
        await _switch_transport(mode)
    except Exception as exc:
        raise HTTPException(500, f"Failed to switch transport to {mode!r}: {exc}")

    del _transport_requests[req_id]
    return {"ok": True, "transport_mode": mode}


@router.post("/transport-requests/{req_id}/reject")
async def reject_transport_request(req_id: str) -> dict:
    """Reject a transport-switch request without switching."""
    _transport_requests.pop(req_id, None)
    return {"ok": True}


@router.post("/request-transport")
async def request_transport_from_peer(
    target_peer_id: str,
    requested_transport: str,
) -> dict:
    """Ask a remote peer (via their agent API) to switch transport."""
    settings = get_settings()
    effective_pid = token_store.get_peer_id() or settings.PEER_ID

    try:
        peer = await server_client.get_peer(target_peer_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    api_url: str = peer["api_url"]

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            r = await client.post(
                f"{api_url}/transfer/transport-request",
                json={
                    "sender_peer_id": effective_pid,
                    "requested_transport": requested_transport,
                },
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                502,
                f"Remote peer returned {exc.response.status_code}: {exc.response.text}",
            )
        except httpx.RequestError as exc:
            raise HTTPException(502, f"Cannot reach peer {target_peer_id!r}: {exc}")


# ── Incoming QUIC connection management ───────────────────────────────────────

@router.get("/incoming", response_model=list[IncomingConnection])
async def list_incoming() -> list[IncomingConnection]:
    """Return pending/accepted/rejected incoming QUIC connections with cert info."""
    transport = get_transport()
    if not isinstance(transport, QUICTransport):
        return []
    return [IncomingConnection(**c) for c in transport.list_pending()]


@router.post("/incoming/{transfer_id}/accept")
async def accept_incoming(transfer_id: str) -> dict:
    """Approve an incoming QUIC connection — the buffered RS blocks will be decoded."""
    transport = get_transport()
    if not isinstance(transport, QUICTransport):
        raise HTTPException(400, "Not running QUIC transport")
    if transfer_id not in transport._pending_conns:
        raise HTTPException(404, "Incoming connection not found")
    transport.approve_connection(transfer_id)
    return {"ok": True}


@router.post("/incoming/{transfer_id}/reject")
async def reject_incoming(transfer_id: str) -> dict:
    """Reject an incoming QUIC connection — buffered packets are discarded."""
    transport = get_transport()
    if not isinstance(transport, QUICTransport):
        raise HTTPException(400, "Not running QUIC transport")
    if transfer_id not in transport._pending_conns:
        raise HTTPException(404, "Incoming connection not found")
    transport.reject_connection(transfer_id)
    return {"ok": True}
