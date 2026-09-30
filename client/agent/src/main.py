from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import config_store
from config import get_settings
from config_router import router as config_router
from files.router import router as files_router
from metrics.probe import rtt_probe_loop
from peers.router import router as peers_router
from rs.transport import QUICTransport, UDPTransport, get_transport, set_transport
from server_client import server_client
from metrics.otel import setup_otel, init_custom_metrics
import storage.db as db
import token_store
from transfers.router import router as transfers_router

_HEARTBEAT_INTERVAL_S = 15
_auth_store: dict = {}


async def _apply_server_incoming_policy(peer_id: str) -> None:
    """Pull admin-configured incoming policy from the server and apply to config_store."""
    try:
        policy_data = await server_client.get_incoming_policy(peer_id)
        if not policy_data:
            return
        changes: dict = {}
        if "incoming_policy" in policy_data:
            changes["incoming_policy"] = policy_data["incoming_policy"]
        if "incoming_allowed_peers" in policy_data:
            changes["incoming_allowed_peers"] = ",".join(policy_data["incoming_allowed_peers"])
        if changes:
            config_store.update(changes)
            config_store.save()
    except Exception:
        pass


async def _heartbeat_loop() -> None:
    consecutive_failures = 0
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
        settings = get_settings()
        pid = token_store.get_peer_id() or config_store.get("peer_id", settings.PEER_ID)

        async def _reregister() -> None:
            try:
                transport = token_store.get_transport_mode() or config_store.get("transport_mode", settings.TRANSPORT_MODE)
                udp_host = config_store.get("udp_advertise_host", "") or _effective_advertise_host()
                result = await server_client.register(
                    peer_id=pid,
                    api_url=config_store.get("agent_api_url", "") or settings.AGENT_API_URL,
                    udp_host=udp_host,
                    udp_port=config_store.get("udp_port", settings.UDP_PORT),
                    transport=transport,
                )
                token_store.set_peer_id(result.get("peer_id", pid))
            except Exception:
                pass

        try:
            await server_client.heartbeat(pid)
            consecutive_failures = 0
        except httpx.HTTPStatusError as exc:
            consecutive_failures += 1
            if exc.response.status_code == 404:
                await _reregister()
                consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= 2:
                await _reregister()


def _effective_advertise_host() -> str:
    import socket
    stored = config_store.get("udp_advertise_host", "")
    if stored:
        return stored
    udp_host = config_store.get("udp_host", "0.0.0.0")
    if udp_host in ("0.0.0.0", "::"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
    return udp_host


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    config_store.load({
        "server_url": settings.SERVER_URL,
        "peer_id": settings.PEER_ID,
        "agent_api_url": settings.AGENT_API_URL,
        "udp_host": settings.UDP_HOST,
        "udp_port": settings.UDP_PORT,
        "udp_advertise_host": settings.UDP_ADVERTISE_HOST,
        "transport_mode": settings.TRANSPORT_MODE,
        "storage_path": settings.STORAGE_PATH,
        "invite_token": settings.INVITE_TOKEN,
        "network_hint": settings.NETWORK_HINT,
        "incoming_policy": settings.INCOMING_POLICY,
        "incoming_allowed_peers": settings.INCOMING_ALLOWED_PEERS,
        "incoming_denied_peers": settings.INCOMING_DENIED_PEERS,
    })

    await db.init_db(config_store.get("storage_path"))

    transport_mode = config_store.get("transport_mode", "udp")
    if transport_mode == "quic":
        set_transport(QUICTransport())
    else:
        set_transport(UDPTransport())
    await get_transport().start(
        config_store.get("udp_host", "0.0.0.0"),
        config_store.get("udp_port", 9001),
    )

    if settings.AGENT_SERVICE_TOKEN or config_store.get("invite_token", ""):
        try:
            pid = config_store.get("peer_id", settings.PEER_ID)
            result = await server_client.register(
                peer_id=pid,
                api_url=config_store.get("agent_api_url", "") or settings.AGENT_API_URL,
                udp_host=_effective_advertise_host(),
                udp_port=config_store.get("udp_port", settings.UDP_PORT),
                transport=transport_mode,
            )
            registered_pid = result.get("peer_id", pid)
            token_store.set_peer_id(registered_pid)
            await _apply_server_incoming_policy(registered_pid)
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    probe_task = asyncio.create_task(rtt_probe_loop())
    yield
    heartbeat_task.cancel()
    probe_task.cancel()
    get_transport().stop()
    await db.close_db()


app = FastAPI(title="RS Transfer Agent", version="0.1.0", lifespan=lifespan)

# Setup OpenTelemetry
settings = get_settings()
setup_otel(app, service_name=f"rs-agent-{settings.PEER_ID}")
init_custom_metrics()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router, prefix="/config", tags=["config"])
app.include_router(files_router, prefix="/files", tags=["files"])
app.include_router(peers_router, prefix="/peers", tags=["peers"])
app.include_router(transfers_router, prefix="/transfer", tags=["transfer"])


@app.get("/health", tags=["meta"])
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "transport": token_store.get_transport_mode() or config_store.get("transport_mode", settings.TRANSPORT_MODE),
        "udp_host": config_store.get("udp_host", settings.UDP_HOST),
        "udp_port": config_store.get("udp_port", settings.UDP_PORT),
    }


@app.get("/auth/callback", tags=["auth"])
async def auth_callback(code: str, state: str):
    _auth_store["last"] = {"code": code, "state": state}
    return HTMLResponse("""
        <html>
            <body style="font-family:sans-serif;text-align:center;padding-top:50px;background:#0f172a;color:#cbd5e1;">
                <h1 style="color:#10b981;">&#10003; Autenticación Exitosa</h1>
                <p>Ya podés cerrar esta pestaña y volver a RockDove.</p>
                <script>setTimeout(() => window.close(), 3000);</script>
            </body>
        </html>
    """)


@app.get("/auth/poll", tags=["auth"])
async def auth_poll():
    return _auth_store.pop("last", None)


class TokenPayload(BaseModel):
    token: str
    server_url: str | None = None


def _decode_jwt_claims(token: str) -> dict:
    try:
        import base64, json as _json
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return _json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def _peer_id_from_jwt(token: str, fallback: str) -> str:
    claims = _decode_jwt_claims(token)
    return claims.get("preferred_username") or claims.get("sub") or fallback


def _preferred_username_from_jwt(token: str) -> str | None:
    claims = _decode_jwt_claims(token)
    return claims.get("preferred_username") or None


@app.post("/auth/token", tags=["auth"])
async def push_token(body: TokenPayload):
    token_store.set_token(body.token)
    if body.server_url:
        token_store.set_server_url(body.server_url)
        config_store.update({"server_url": body.server_url})
        config_store.save()
    settings = get_settings()
    peer_id = _peer_id_from_jwt(body.token, config_store.get("peer_id", settings.PEER_ID))
    # preferred_username doubles as the owner display name for multi-device grouping
    owner = _preferred_username_from_jwt(body.token)
    try:
        result = await server_client.register(
            peer_id=peer_id,
            api_url=config_store.get("agent_api_url", "") or settings.AGENT_API_URL,
            udp_host=_effective_advertise_host(),
            udp_port=config_store.get("udp_port", settings.UDP_PORT),
            transport=config_store.get("transport_mode", settings.TRANSPORT_MODE),
            owner=owner or settings.PEER_OWNER or None,
        )
        registered_pid = result.get("peer_id", peer_id)
        token_store.set_peer_id(registered_pid)
        await _apply_server_incoming_policy(registered_pid)
    except Exception:
        pass
    return {"ok": True}
