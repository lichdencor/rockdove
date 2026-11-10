from __future__ import annotations

import socket
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config_store
import token_store
from config import get_settings
from rs.transport import QUICTransport, UDPTransport, get_transport, set_transport
from server_client import server_client

router = APIRouter()

_TRANSPORT_FIELDS = frozenset({"transport_mode", "udp_host", "udp_port"})
_REGISTER_FIELDS = frozenset({
    "server_url", "peer_id", "agent_api_url",
    "udp_host", "udp_port", "udp_advertise_host", "transport_mode",
})


def _detect_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _effective_agent_api_url() -> str:
    stored = config_store.get("agent_api_url", "")
    if stored:
        return stored
    return get_settings().AGENT_API_URL


def _effective_advertise_host() -> str:
    stored = config_store.get("udp_advertise_host", "")
    if stored:
        return stored
    udp_host = config_store.get("udp_host", "0.0.0.0")
    if udp_host in ("0.0.0.0", "::"):
        return _detect_local_ip()
    return udp_host


class FullConfigResponse(BaseModel):
    server_url: str
    peer_id: str
    agent_api_url: str
    udp_host: str
    udp_port: int
    udp_advertise_host: str
    transport_mode: str
    storage_path: str
    invite_token: str
    network_hint: str
    incoming_policy: str
    incoming_allowed_peers: str
    incoming_denied_peers: str


class FullConfigUpdateRequest(BaseModel):
    server_url: Optional[str] = None
    peer_id: Optional[str] = None
    agent_api_url: Optional[str] = None
    udp_host: Optional[str] = None
    udp_port: Optional[int] = None
    udp_advertise_host: Optional[str] = None
    transport_mode: Optional[Literal["udp", "quic"]] = None
    storage_path: Optional[str] = None
    invite_token: Optional[str] = None
    network_hint: Optional[str] = None
    incoming_policy: Optional[Literal["allow_all", "deny_all", "allow_list", "deny_list"]] = None
    incoming_allowed_peers: Optional[str] = None
    incoming_denied_peers: Optional[str] = None


class FullConfigUpdateResponse(BaseModel):
    ok: bool
    requires_restart: bool
    transport_mode: str


@router.get("", response_model=FullConfigResponse)
async def get_config() -> FullConfigResponse:
    settings = get_settings()
    return FullConfigResponse(
        server_url=config_store.get("server_url", settings.SERVER_URL),
        peer_id=token_store.get_peer_id() or config_store.get("peer_id", settings.PEER_ID),
        agent_api_url=_effective_agent_api_url(),
        udp_host=config_store.get("udp_host", settings.UDP_HOST),
        udp_port=config_store.get("udp_port", settings.UDP_PORT),
        udp_advertise_host=_effective_advertise_host(),
        transport_mode=token_store.get_transport_mode() or config_store.get("transport_mode", settings.TRANSPORT_MODE),
        storage_path=config_store.get("storage_path", settings.STORAGE_PATH),
        invite_token=config_store.get("invite_token", settings.INVITE_TOKEN),
        network_hint=config_store.get("network_hint", settings.NETWORK_HINT),
        incoming_policy=config_store.get("incoming_policy", settings.INCOMING_POLICY),
        incoming_allowed_peers=config_store.get("incoming_allowed_peers", settings.INCOMING_ALLOWED_PEERS),
        incoming_denied_peers=config_store.get("incoming_denied_peers", settings.INCOMING_DENIED_PEERS),
    )


@router.put("", response_model=FullConfigUpdateResponse)
async def update_config(body: FullConfigUpdateRequest) -> FullConfigUpdateResponse:
    settings = get_settings()
    changes = {k: v for k, v in body.model_dump().items() if v is not None}

    if not changes:
        return FullConfigUpdateResponse(
            ok=True,
            requires_restart=False,
            transport_mode=token_store.get_transport_mode() or config_store.get("transport_mode", settings.TRANSPORT_MODE),
        )

    needs_transport_rebind = bool(_TRANSPORT_FIELDS & changes.keys())
    needs_reregister = bool(_REGISTER_FIELDS & changes.keys())
    requires_restart = "storage_path" in changes

    old_snapshot = config_store.get_all()
    config_store.update(changes)
    config_store.save()

    if needs_transport_rebind:
        new_mode = config_store.get("transport_mode", settings.TRANSPORT_MODE)
        new_udp_host = config_store.get("udp_host", settings.UDP_HOST)
        new_udp_port = config_store.get("udp_port", settings.UDP_PORT)
        old_mode = old_snapshot.get("transport_mode", settings.TRANSPORT_MODE)
        old_udp_host = old_snapshot.get("udp_host", settings.UDP_HOST)
        old_udp_port = old_snapshot.get("udp_port", settings.UDP_PORT)

        old_transport = get_transport()
        new_transport = QUICTransport() if new_mode == "quic" else UDPTransport()
        old_transport.stop()
        try:
            set_transport(new_transport)
            await new_transport.start(new_udp_host, new_udp_port)
        except Exception as exc:
            config_store.update(old_snapshot)
            config_store.save()
            set_transport(old_transport)
            try:
                await old_transport.start(old_udp_host, old_udp_port)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(exc))

        token_store.set_transport_mode(new_mode)

    if "server_url" in changes:
        token_store.set_server_url(changes["server_url"])

    if needs_reregister:
        pid = token_store.get_peer_id() or config_store.get("peer_id", settings.PEER_ID)
        try:
            result = await server_client.register(
                peer_id=pid,
                api_url=_effective_agent_api_url(),
                udp_host=_effective_advertise_host(),
                udp_port=config_store.get("udp_port", settings.UDP_PORT),
                transport=config_store.get("transport_mode", settings.TRANSPORT_MODE),
            )
            token_store.set_peer_id(result.get("peer_id", pid))
        except Exception:
            pass

    return FullConfigUpdateResponse(
        ok=True,
        requires_restart=requires_restart,
        transport_mode=token_store.get_transport_mode() or config_store.get("transport_mode", settings.TRANSPORT_MODE),
    )
