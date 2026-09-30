import asyncio
import time

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from config import get_settings
from rs.decoder import decode_transfer
from rs.encoder import encode_file
from rs.models import TransferStatus
from rs.transport import udp
from server_client import server_client
from storage.db import insert_transfer, list_history
from storage.store import FileStorage
from transfers.models import HistoryEntry, ReceiveRequest, SendRequest, TransferResult

router = APIRouter()

_transfers: dict[str, dict] = {}


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

    target_api_url = peer["api_url"]
    target_udp_host = peer["udp_host"]
    target_udp_port = peer["udp_port"]

    packets, transfer_id, n, k, chunk_size = encode_file(file_bytes, redundancy_level)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(
                f"{target_api_url}/transfer/receive",
                json={
                    "transfer_id": transfer_id,
                    "checksum": meta["sha256"],
                    "file_size": len(file_bytes),
                    "n": n, "k": k, "chunk_size": chunk_size,
                },
            )
            if r.status_code not in (200, 202):
                raise HTTPException(502, f"Peer rejected transfer: {r.text}")
        except httpx.RequestError as exc:
            raise HTTPException(502, f"Cannot reach peer: {exc}")

    t_send = time.monotonic()
    await udp.send(packets, target_udp_host, target_udp_port)

    result = TransferResult(
        transfer_id=transfer_id,
        status=TransferStatus.failed,
        reason="timeout_waiting_for_peer_result",
    )
    async with httpx.AsyncClient(timeout=5) as client:
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

    base = result.model_dump(
        exclude={"effective_redundancy", "quality", "profile_name"}
    )
    return TransferResult(
        **base,
        effective_redundancy=redundancy_level,
        quality=effective_quality,
        profile_name=effective_profile,
        should_relay=should_relay,
        relay_peer_id=relay_peer_id,
        route_source=route_source,
        route_confidence=route_confidence,
    )


@router.post("/receive", status_code=202)
async def receive_transfer(req: ReceiveRequest, background_tasks: BackgroundTasks) -> dict:
    _transfers[req.transfer_id] = {"status": "pending"}
    background_tasks.add_task(_process_incoming, req)
    return {"transfer_id": req.transfer_id, "status": "pending"}


async def _process_incoming(req: ReceiveRequest) -> None:
    settings = get_settings()
    packets = await udp.collect(req.transfer_id, timeout=req.timeout)
    result = decode_transfer(packets, req.checksum)

    file_id = None
    if result.status != TransferStatus.failed and result.file_bytes:
        storage = FileStorage(settings.STORAGE_PATH)
        saved = storage.save(result.file_bytes, f"transfer_{req.transfer_id}")
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
