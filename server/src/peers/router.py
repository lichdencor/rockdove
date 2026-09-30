"""
Central peer registry backed by Redis.

Keys:
  peer:{org_id}:{peer_id}   → hash  (TTL = HEARTBEAT_TTL_S)
  scope:{org_id}            → JSON  {group: [visible_groups, ...]}

Visibility rules (OIDC mode):
  - Peers are isolated by org_id (realm). Cross-org visibility is impossible.
  - Within an org, visibility is governed by the scope config:
      "__all__" sentinel  → see every peer in the org
      list of groups      → see peers whose group appears in the list
      no entry for group  → default: see only peers in the same group
  - Admin (OIDC_ADMIN_GROUP) bypasses scope checks and sees the entire org.

Dev mode (OIDC_ENABLED=False):
  - org_id is always "dev", no scope filtering, all peers visible.

WebSocket /peers/watch:
  - Authenticated via ?token=<jwt> query parameter in OIDC mode.
  - Falls back to full-org view in dev mode.
  - Client passes JWT as ?token= when connecting (OIDC mode).
"""
import asyncio
import json
import httpx
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from auth.deps import CallerInfo, extract_auth
from config import get_settings
from invites.router import validate_invite
from redis_client import get_redis
from neo4j_client import get_neo4j

router = APIRouter()

_watchers: dict[str, set[WebSocket]] = {}


# ── Models ────────────────────────────────────────────────────────────────────

class PeerRegistration(BaseModel):
    peer_id: str
    api_url: str
    udp_host: str
    udp_port: int = 9001
    network_hint: str = "auto"
    group: str = "default"
    invite_token: str | None = None
    transport: str = "udp"  # "udp" | "quic"
    relay_capable: bool = False
    relay_tags: list[str] = []  # "ephemeral" | "restricted" | "gateway"
    owner: str | None = None    # display name for multi-device grouping


class PeerInfo(BaseModel):
    peer_id: str
    api_url: str
    udp_host: str
    udp_port: int
    last_seen: str
    online: bool
    group: str = "default"
    org_id: str = "dev"
    transport: str = "udp"  # "udp" | "quic"
    relay_capable: bool = False
    relay_tags: list[str] = []
    owner: str | None = None
    # Server-admin-configured incoming policy (for headless peers)
    incoming_policy: str = "allow_all"
    incoming_allowed_peers: list[str] = []


class RelayConfig(BaseModel):
    relay_capable: bool
    relay_tags: list[str] = []
    relay_allowed_peers: list[str] = []
    relay_allowed_groups: list[str] = []


class IncomingPolicyConfig(BaseModel):
    incoming_policy: str = "allow_all"  # "allow_all"|"deny_all"|"allow_list"
    incoming_allowed_peers: list[str] = []


class ScopeConfig(BaseModel):
    scopes: dict[str, list[str]]
    """
    Maps each group name to the list of group names it is allowed to see.
    Use "__all__" as a value to grant visibility over the entire org.
    Example:
      {"admin": ["__all__"], "hq": ["hq", "finance"], "field": ["field"]}
    """


# ── Scope helpers ─────────────────────────────────────────────────────────────

async def _get_scope(org_id: str) -> dict[str, list[str]]:
    r = get_redis()
    raw = await r.get(f"scope:{org_id}")
    return json.loads(raw) if raw else {}


async def _visible_groups(
    caller: CallerInfo, scope: dict[str, list[str]]
) -> list[str] | None:
    """
    Returns the set of group names the caller may see, or None for unrestricted.
    None means "all peers in the org" (admin / dev mode).
    """
    settings = get_settings()
    if not settings.OIDC_ENABLED or caller.is_admin:
        return None

    allowed: set[str] = set()
    for group in caller.groups:
        vis = scope.get(group)
        if vis is None:
            allowed.add(group)          # default: same group only
        elif "__all__" in vis:
            return None                 # can see everything
        else:
            allowed.update(vis)

    if not caller.groups:
        allowed.add("default")

    return list(allowed)


# ── Redis snapshot ────────────────────────────────────────────────────────────

def _compute_online(last_seen_iso: str, timeout_s: int) -> bool:
    """Returns True if last_seen is within timeout_s seconds of now."""
    try:
        last_seen = datetime.fromisoformat(last_seen_iso)
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last_seen).total_seconds() < timeout_s
    except Exception:
        return False


async def _snapshot(org_id: str, caller: CallerInfo) -> list[dict]:
    driver = get_neo4j()
    scope = await _get_scope(org_id)
    visible = await _visible_groups(caller, scope)
    timeout_s = get_settings().HEARTBEAT_TIMEOUT_S

    query = (
        "MATCH (p:Peer {org_id: $org_id}) "
        "RETURN p"
    )
    
    result = []
    async with driver.session() as session:
        records = await session.run(query, org_id=org_id)
        async for record in records:
            p = record["p"]
            peer_group = p.get("group", "default")
            if visible is not None and peer_group not in visible:
                continue
            
            last_seen = p.get("last_seen", "")
            relay_tags_raw = p.get("relay_tags", "")
            allowed_raw = p.get("incoming_allowed_peers", "")
            result.append({
                "peer_id": p["peer_id"],
                "api_url": p["api_url"],
                "udp_host": p["udp_host"],
                "udp_port": int(p["udp_port"]),
                "last_seen": last_seen,
                "online": _compute_online(last_seen, timeout_s),
                "group": peer_group,
                "org_id": org_id,
                "transport": p.get("transport", "udp"),
                "relay_capable": p.get("relay_capable", False),
                "relay_tags": relay_tags_raw.split(",") if relay_tags_raw else [],
                "owner": p.get("owner") or None,
                "incoming_policy": p.get("incoming_policy", "allow_all"),
                "incoming_allowed_peers": allowed_raw.split(",") if allowed_raw else [],
            })
    return result


async def _broadcast(org_id: str, caller: CallerInfo) -> None:
    watchers = _watchers.get(org_id, set())
    if not watchers:
        return
    # Broadcast uses an admin-level snapshot so all subscribers get the full list;
    # scope enforcement happens per-connection in the WebSocket handler.
    admin_caller = CallerInfo(peer_id=None, is_service=True, org_id=org_id)
    payload = json.dumps(await _snapshot(org_id, admin_caller))
    dead: set[WebSocket] = set()
    for ws in list(watchers):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    watchers -= dead


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.post("/register", response_model=PeerInfo)
async def register(
    reg: PeerRegistration,
    caller: CallerInfo = Depends(extract_auth),
) -> PeerInfo:
    settings = get_settings()

    if caller.peer_id:
        effective_peer_id = caller.peer_id
    elif caller.is_service:
        effective_peer_id = reg.peer_id
    elif reg.invite_token:
        await validate_invite(reg.invite_token)
        effective_peer_id = reg.peer_id
    elif not settings.OIDC_ENABLED:
        effective_peer_id = reg.peer_id
    else:
        raise HTTPException(401, "Authentication required")

    # In OIDC mode the group comes from the first JWT group; body group used in dev.
    effective_group = (
        caller.groups[0] if (settings.OIDC_ENABLED and caller.groups) else reg.group
    )
    # Owner: in OIDC mode use the caller identity (preferred_username = peer_id for human users)
    # In dev mode use the registration body, fallback to peer_id
    effective_owner = (
        caller.peer_id if (settings.OIDC_ENABLED and caller.peer_id) else (reg.owner or effective_peer_id)
    )

    driver = get_neo4j()
    now = datetime.now(timezone.utc).isoformat()

    query = (
        "MERGE (p:Peer {peer_id: $peer_id, org_id: $org_id}) "
        "SET p += { "
        "  api_url: $api_url, "
        "  udp_host: $udp_host, "
        "  udp_port: $udp_port, "
        "  last_seen: $last_seen, "
        "  network_hint: $network_hint, "
        "  group: $group, "
        "  transport: $transport, "
        "  relay_capable: $relay_capable, "
        "  relay_tags: $relay_tags, "
        "  owner: $owner "
        "} "
        "RETURN p"
    )

    async with driver.session() as session:
        await session.run(
            query,
            peer_id=effective_peer_id,
            org_id=caller.org_id,
            api_url=reg.api_url,
            udp_host=reg.udp_host,
            udp_port=reg.udp_port,
            last_seen=now,
            network_hint=reg.network_hint,
            group=effective_group,
            transport=reg.transport,
            relay_capable=reg.relay_capable,
            relay_tags=",".join(reg.relay_tags),
            owner=effective_owner,
        )

    await _broadcast(caller.org_id, caller)
    return PeerInfo(
        peer_id=effective_peer_id,
        api_url=reg.api_url,
        udp_host=reg.udp_host,
        udp_port=reg.udp_port,
        last_seen=now,
        online=True,
        group=effective_group,
        org_id=caller.org_id,
        transport=reg.transport,
        relay_capable=reg.relay_capable,
        relay_tags=reg.relay_tags,
        owner=effective_owner,
    )


@router.post("/{peer_id}/heartbeat")
async def heartbeat(
    peer_id: str,
    caller: CallerInfo = Depends(extract_auth),
) -> dict:
    driver = get_neo4j()
    now = datetime.now(timezone.utc).isoformat()
    
    query = (
        "MATCH (p:Peer {peer_id: $peer_id, org_id: $org_id}) "
        "SET p.last_seen = $now "
        "RETURN p"
    )
    
    async with driver.session() as session:
        result = await session.run(query, peer_id=peer_id, org_id=caller.org_id, now=now)
        if not await result.single():
            raise HTTPException(404, "Peer not registered")

    await _broadcast(caller.org_id, caller)
    return {"status": "ok"}


@router.get("/", response_model=list[PeerInfo])
async def list_peers(
    caller: CallerInfo = Depends(extract_auth),
) -> list[PeerInfo]:
    return [PeerInfo(**p) for p in await _snapshot(caller.org_id, caller)]


@router.get("/scopes", response_model=ScopeConfig)
async def get_scopes(
    caller: CallerInfo = Depends(extract_auth),
) -> ScopeConfig:
    if get_settings().OIDC_ENABLED and not caller.is_admin:
        raise HTTPException(403, "Admin required")
    return ScopeConfig(scopes=await _get_scope(caller.org_id))


@router.put("/scopes", response_model=ScopeConfig)
async def set_scopes(
    body: ScopeConfig,
    caller: CallerInfo = Depends(extract_auth),
) -> ScopeConfig:
    if get_settings().OIDC_ENABLED and not caller.is_admin:
        raise HTTPException(403, "Admin required")
    r = get_redis()
    await r.set(f"scope:{caller.org_id}", json.dumps(body.scopes))
    return body


@router.get("/relay", response_model=PeerInfo)
async def get_relay_peer(
    target: str,
    caller: CallerInfo = Depends(extract_auth),
) -> PeerInfo:
    """Return the best available relay peer to reach `target` (relay_capable=true, same org, online)."""
    driver = get_neo4j()
    timeout_s = get_settings().HEARTBEAT_TIMEOUT_S
    query = (
        "MATCH (p:Peer {org_id: $org_id}) "
        "WHERE p.relay_capable = true "
        "  AND p.peer_id <> $target "
        "  AND p.peer_id <> $caller "
        "RETURN p ORDER BY p.last_seen DESC LIMIT 1"
    )
    async with driver.session() as session:
        result = await session.run(
            query,
            org_id=caller.org_id,
            target=target,
            caller=caller.peer_id or "",
        )
        record = await result.single()
        if not record:
            raise HTTPException(404, "No relay peer available")
        p = record["p"]
        last_seen = p.get("last_seen", "")
        if not _compute_online(last_seen, timeout_s):
            raise HTTPException(404, "No online relay peer available")
        relay_tags_raw = p.get("relay_tags", "")
        return PeerInfo(
            peer_id=p["peer_id"],
            api_url=p["api_url"],
            udp_host=p["udp_host"],
            udp_port=int(p["udp_port"]),
            last_seen=last_seen,
            online=True,
            group=p.get("group", "default"),
            org_id=caller.org_id,
            transport=p.get("transport", "udp"),
            relay_capable=True,
            relay_tags=relay_tags_raw.split(",") if relay_tags_raw else [],
        )


@router.get("/{peer_id}/incoming-policy")
async def get_incoming_policy(
    peer_id: str,
    caller: CallerInfo = Depends(extract_auth),
) -> dict:
    """Return the admin-configured incoming transfer policy for a peer."""
    driver = get_neo4j()
    query = (
        "MATCH (p:Peer {peer_id: $peer_id, org_id: $org_id}) "
        "RETURN p.incoming_policy AS policy, p.incoming_allowed_peers AS allowed"
    )
    async with driver.session() as session:
        result = await session.run(query, peer_id=peer_id, org_id=caller.org_id)
        record = await result.single()
        if not record:
            raise HTTPException(404, "Peer not found")
        allowed_raw = record["allowed"] or ""
        return {
            "incoming_policy": record["policy"] or "allow_all",
            "incoming_allowed_peers": [p for p in allowed_raw.split(",") if p],
        }


@router.post("/{peer_id}/incoming-policy")
async def update_incoming_policy(
    peer_id: str,
    body: IncomingPolicyConfig,
    caller: CallerInfo = Depends(extract_auth),
) -> dict:
    """Admin-only: set the incoming transfer policy for a peer (typically a headless agent)."""
    if get_settings().OIDC_ENABLED and not caller.is_admin:
        raise HTTPException(403, "Admin required")
    driver = get_neo4j()
    query = (
        "MATCH (p:Peer {peer_id: $peer_id, org_id: $org_id}) "
        "SET p.incoming_policy = $policy, "
        "    p.incoming_allowed_peers = $allowed "
        "RETURN p.peer_id AS peer_id"
    )
    async with driver.session() as session:
        result = await session.run(
            query,
            peer_id=peer_id,
            org_id=caller.org_id,
            policy=body.incoming_policy,
            allowed=",".join(body.incoming_allowed_peers),
        )
        record = await result.single()
        if not record:
            raise HTTPException(404, "Peer not found")
    await _broadcast(caller.org_id, caller)
    return {"status": "ok", "peer_id": peer_id}


@router.post("/{peer_id}/relay-config")
async def update_relay_config(
    peer_id: str,
    body: RelayConfig,
    caller: CallerInfo = Depends(extract_auth),
) -> dict:
    """Admin-only: configure relay settings for a peer (overrides the peer's self-declared values)."""
    if get_settings().OIDC_ENABLED and not caller.is_admin:
        raise HTTPException(403, "Admin required")
    driver = get_neo4j()
    query = (
        "MATCH (p:Peer {peer_id: $peer_id, org_id: $org_id}) "
        "SET p.relay_capable = $relay_capable, "
        "    p.relay_tags = $relay_tags, "
        "    p.relay_allowed_peers = $relay_allowed_peers, "
        "    p.relay_allowed_groups = $relay_allowed_groups "
        "RETURN p.peer_id as peer_id"
    )
    async with driver.session() as session:
        result = await session.run(
            query,
            peer_id=peer_id,
            org_id=caller.org_id,
            relay_capable=body.relay_capable,
            relay_tags=",".join(body.relay_tags),
            relay_allowed_peers=",".join(body.relay_allowed_peers),
            relay_allowed_groups=",".join(body.relay_allowed_groups),
        )
        record = await result.single()
        if not record:
            raise HTTPException(404, "Peer not found")
    await _broadcast(caller.org_id, caller)
    return {"status": "ok", "peer_id": peer_id}


@router.get("/{peer_id}", response_model=PeerInfo)
async def get_peer(
    peer_id: str,
    caller: CallerInfo = Depends(extract_auth),
) -> PeerInfo:
    driver = get_neo4j()
    query = (
        "MATCH (p:Peer {peer_id: $peer_id, org_id: $org_id}) "
        "RETURN p"
    )
    async with driver.session() as session:
        result = await session.run(query, peer_id=peer_id, org_id=caller.org_id)
        record = await result.single()
        if not record:
            raise HTTPException(404, "Peer not found")
        
        p = record["p"]
        last_seen = p.get("last_seen", "")
        relay_tags_raw = p.get("relay_tags", "")
        allowed_raw = p.get("incoming_allowed_peers", "")
        return PeerInfo(
            peer_id=p["peer_id"],
            api_url=p["api_url"],
            udp_host=p["udp_host"],
            udp_port=int(p["udp_port"]),
            last_seen=last_seen,
            online=_compute_online(last_seen, get_settings().HEARTBEAT_TIMEOUT_S),
            group=p.get("group", "default"),
            org_id=p.get("org_id", caller.org_id),
            transport=p.get("transport", "udp"),
            relay_capable=p.get("relay_capable", False),
            relay_tags=relay_tags_raw.split(",") if relay_tags_raw else [],
            owner=p.get("owner") or None,
            incoming_policy=p.get("incoming_policy", "allow_all"),
            incoming_allowed_peers=[x for x in allowed_raw.split(",") if x] if allowed_raw else [],
        )


@router.delete("/{peer_id}")
async def delete_peer(
    peer_id: str,
    caller: CallerInfo = Depends(extract_auth),
) -> dict:
    if get_settings().OIDC_ENABLED and not caller.is_admin:
        raise HTTPException(403, "Admin required")
    
    driver = get_neo4j()
    query = (
        "MATCH (p:Peer {peer_id: $peer_id, org_id: $org_id}) "
        "DETACH DELETE p"
    )
    async with driver.session() as session:
        await session.run(query, peer_id=peer_id, org_id=caller.org_id)
    
    await _broadcast(caller.org_id, caller)
    return {"status": "ok"}


@router.get("/{peer_id}/metrics")
async def get_peer_metrics(
    peer_id: str,
    caller: CallerInfo = Depends(extract_auth),
) -> dict:
    """Proxy Prometheus metrics from the agent to the UI."""
    driver = get_neo4j()
    query = "MATCH (p:Peer {peer_id: $peer_id, org_id: $org_id}) RETURN p.api_url as api_url"
    async with driver.session() as session:
        result = await session.run(query, peer_id=peer_id, org_id=caller.org_id)
        record = await result.single()
        if not record:
            raise HTTPException(404, "Peer not found")
        api_url = record["api_url"]

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            # We fetch from the agent's /metrics/ endpoint (trailing slash often required by mount)
            # Use rstrip('/') + '/metrics/' to ensure we don't end up with //
            target_url = f"{api_url.rstrip('/')}/metrics/"
            r = await client.get(target_url)
            r.raise_for_status()
            return {"raw": r.text}
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch metrics from agent: {str(e)}")


@router.websocket("/watch")
async def watch_peers(ws: WebSocket) -> None:
    """
    Real-time peer discovery stream.
    OIDC mode: pass the JWT as ?token=<bearer> query parameter.
    Dev mode:  no auth required.
    """
    await ws.accept()

    settings = get_settings()
    org_id = "dev"

    if settings.OIDC_ENABLED:
        token = ws.query_params.get("token", "")
        if not token:
            await ws.close(code=4001, reason="token required")
            return
        from auth.verifier import org_id_from_issuer, verify_token
        try:
            payload = verify_token(token)
            org_id = org_id_from_issuer(payload.get("iss", ""))
        except Exception:
            await ws.close(code=4001, reason="invalid token")
            return

    # WebSocket streams the admin-level snapshot; per-connection scope filtering
    # is a TODO — the client already enforces group labels from each PeerInfo.
    caller = CallerInfo(peer_id=None, is_service=True, org_id=org_id)

    _watchers.setdefault(org_id, set()).add(ws)
    try:
        await ws.send_text(json.dumps(await _snapshot(org_id, caller)))
        while True:
            await asyncio.sleep(10)
            await ws.send_text(json.dumps(await _snapshot(org_id, caller)))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _watchers.get(org_id, set()).discard(ws)
