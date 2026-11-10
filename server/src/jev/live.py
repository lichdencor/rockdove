"""Live peers, link metrics and micro-transfer population for the /jev/ui page."""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import time

import httpx

from auth.deps import CallerInfo
from config import get_settings
from metrics.collector import get_average, get_link_history
from peers.router import _compute_online, _snapshot
from redis_client import get_redis

from .decider import _link_metrics_neo4j

log = logging.getLogger("jev")

_HISTORY_POINTS = 20


async def _redis_peers(org_id: str) -> list[dict]:
    r = get_redis()
    timeout_s = get_settings().HEARTBEAT_TIMEOUT_S
    peers = []
    async for key in r.scan_iter(match=f"peer:{org_id}:*"):
        p = await r.hgetall(key)
        if not p.get("peer_id"):
            continue
        last_seen = p.get("last_seen", "")
        peers.append({
            "peer_id": p["peer_id"],
            "api_url": p.get("api_url", ""),
            "last_seen": last_seen,
            "online": _compute_online(last_seen, timeout_s),
            "group": p.get("group", "default"),
            "relay_capable": p.get("relay_capable") in ("1", "true", "True"),
            "network_hint": p.get("network_hint", "auto"),
        })
    return peers


async def list_peers(caller: CallerInfo) -> tuple[list[dict], str]:
    try:
        return await _snapshot(caller.org_id, caller), "neo4j"
    except Exception as exc:
        log.warning("Neo4j peers unavailable, using Redis registrations: %s", exc)
        return await _redis_peers(caller.org_id), "redis"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


async def link_metrics(a: str, b: str, online: dict[str, bool]) -> tuple[dict, list[dict]]:
    reachable = bool(online.get(a) and online.get(b))
    hist = (await get_link_history(a, b))[-_HISTORY_POINTS:]
    points = [{"t": h.get("recorded_at"), "rtt_ms": round(h["rtt_ms"], 1), "loss_rate": round(h["loss_rate"], 4)}
              for h in hist]
    if hist:
        return {"rtt_ms": round(_mean([h["rtt_ms"] for h in hist]), 1),
                "jitter_ms": round(_mean([h["jitter_ms"] for h in hist]), 1),
                "loss_rate": round(_mean([h["loss_rate"] for h in hist]), 4),
                "reachable": reachable, "samples": len(hist), "origin": f"medido P2P ({len(hist)} muestras)"}, points
    edge = await _link_metrics_neo4j(a, b)
    if edge:
        return {"rtt_ms": round(edge["rtt_ms"], 1), "jitter_ms": round(edge["jitter_ms"], 1),
                "loss_rate": round(edge["loss_rate"], 4), "reachable": reachable, "samples": 1,
                "origin": "medido P2P (último, Neo4j)"}, points
    avgs = [x for x in (await get_average(a), await get_average(b)) if x]
    if avgs:
        # worst of the two peers' server-relative probes approximates the link
        return {"rtt_ms": round(max(x["rtt_ms"] for x in avgs), 1),
                "jitter_ms": round(max(x["jitter_ms"] for x in avgs), 1),
                "loss_rate": round(max(x["loss_rate"] for x in avgs), 4),
                "reachable": reachable, "samples": 0, "origin": "estimado (vs server)"}, points
    return {"rtt_ms": None, "jitter_ms": None, "loss_rate": None, "reachable": reachable, "samples": 0,
            "origin": "sin datos"}, points


async def route_links(source: str, relay: str, target: str, caller: CallerInfo) -> tuple[dict, dict, dict]:
    peers, _ = await list_peers(caller)
    online = {p["peer_id"]: bool(p.get("online")) for p in peers}
    links, history = {}, {}
    for key, a, b in (("direct", source, target), ("source_to_relay", source, relay), ("relay_to_target", relay, target)):
        links[key], history[key] = await link_metrics(a, b, online)
    status = {pid: ("online" if online.get(pid) else "offline") for pid in (source, relay, target)}
    return links, status, history


async def _micro_transfer(client: httpx.AsyncClient, src: dict, dst_id: str, size_kb: int, redundancy: float) -> dict:
    out = {"source": src["peer_id"], "target": dst_id}
    t0 = time.monotonic()
    try:
        up = await client.post(f"{src['api_url']}/files/",
                               files={"file": (f"jev-probe-{dst_id}.bin", os.urandom(size_kb * 1024))})
        up.raise_for_status()
        file_id = up.json()["file_id"]
        try:
            r = await client.post(f"{src['api_url']}/transfer/send",
                                  json={"file_id": file_id, "target_peer_id": dst_id, "redundancy_level": redundancy})
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code != 200:
                out.update(status="error", error=f"{r.status_code}: {body.get('detail', r.text[:200])}")
            else:
                out.update(status=body.get("status"), recovered=body.get("recovered_blocks"),
                           total=body.get("total_blocks"), via_relay=body.get("via_relay"))
        finally:
            await client.delete(f"{src['api_url']}/files/{file_id}")
    except Exception as exc:
        out.update(status="error", error=str(exc)[:200])
    out["elapsed_ms"] = round((time.monotonic() - t0) * 1000)
    return out


async def populate(peer_ids: list[str], caller: CallerInfo, *, rounds: int, size_kb: int,
                   redundancy: float) -> list[dict]:
    """Run small transfers between every ordered pair of the given peers so links get measured."""
    peers, _ = await list_peers(caller)
    by_id = {p["peer_id"]: p for p in peers}
    missing = [pid for pid in peer_ids if pid not in by_id]
    if missing:
        raise ValueError(f"peers desconocidos: {missing}")
    offline = [pid for pid in peer_ids if not by_id[pid].get("online")]
    if offline:
        raise ValueError(f"peers offline: {offline}")
    pairs = list(itertools.permutations(peer_ids, 2))
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for rnd in range(1, rounds + 1):
            batch = await asyncio.gather(*(_micro_transfer(client, by_id[s], d, size_kb, redundancy) for s, d in pairs))
            results += [{**x, "round": rnd} for x in batch]
    return results
