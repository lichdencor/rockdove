from fastapi import APIRouter, Depends

from auth.deps import CallerInfo, extract_auth
from neo4j_client import get_neo4j
from redis_client import get_redis
from .collector import get_average, store_report
from .models import MetricReport, RecommendationResponse
from .recommender import compute_recommendation

router = APIRouter()

_DEFAULT_REDUNDANCY = 0.25
_DEFAULT_QUALITY = "unknown"


@router.post("/report")
async def report_metrics(report: MetricReport) -> dict:
    await store_report(report)
    return {"status": "ok"}


@router.get("/recommendation/{peer_id}", response_model=RecommendationResponse)
async def get_recommendation(peer_id: str) -> RecommendationResponse:
    avg = await get_average(peer_id)

    r = get_redis()
    peer_data = await r.hgetall(f"peer:{peer_id}")
    network_hint = peer_data.get("network_hint", "auto") or "auto"

    if not avg:
        return RecommendationResponse(
            peer_id=peer_id,
            redundancy_level=_DEFAULT_REDUNDANCY,
            quality=_DEFAULT_QUALITY,
            based_on_samples=0,
            profile_name="unknown",
        )

    level, quality, profile_name = compute_recommendation(
        rtt_ms=avg["rtt_ms"],
        jitter_ms=avg["jitter_ms"],
        loss_rate=avg["loss_rate"],
        network_hint=network_hint,
    )
    return RecommendationResponse(
        peer_id=peer_id,
        redundancy_level=level,
        quality=quality,
        based_on_samples=avg["samples"],
        profile_name=profile_name,
    )


@router.get("/history/{peer_id}")
async def get_metric_history(peer_id: str) -> dict:
    """Return the last N raw metric samples for a peer (oldest-first)."""
    r = get_redis()
    key = f"metrics:{peer_id}"
    items_raw = await r.lrange(key, 0, -1)
    if not items_raw:
        return {"peer_id": peer_id, "samples": []}
    # LPUSH stores newest at index 0 → reverse to get chronological order
    samples = [MetricReport.model_validate_json(raw).model_dump() for raw in reversed(items_raw)]
    return {"peer_id": peer_id, "samples": samples}


@router.get("/network-graph")
async def get_network_graph(
    caller: CallerInfo = Depends(extract_auth),
) -> dict:
    """Return all P2P CONNECTS_TO edges for the caller's org (from Neo4j)."""
    driver = get_neo4j()
    query = (
        "MATCH (a:Peer {org_id: $org_id})-[r:CONNECTS_TO]->(b:Peer {org_id: $org_id}) "
        "RETURN a.peer_id AS source, b.peer_id AS target, "
        "       r.rtt_ms AS rtt_ms, r.jitter_ms AS jitter_ms, "
        "       r.loss_rate AS loss_rate, toString(r.updated_at) AS updated_at"
    )
    edges = []
    async with driver.session() as session:
        result = await session.run(query, org_id=caller.org_id)
        async for record in result:
            edges.append({
                "source": record["source"],
                "target": record["target"],
                "rtt_ms": record["rtt_ms"],
                "jitter_ms": record["jitter_ms"],
                "loss_rate": record["loss_rate"],
                "updated_at": record["updated_at"],
            })
    return {"edges": edges}
