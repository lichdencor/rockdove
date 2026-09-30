from datetime import datetime, timezone

from redis_client import get_redis
from neo4j_client import get_neo4j

from .models import MetricReport

_MAX_REPORTS = 10


async def store_report(report: MetricReport) -> None:
    report = report.model_copy(update={"recorded_at": datetime.now(timezone.utc).isoformat()})

    # 1. Store in Redis for recommendation history (single-hop / server-relative)
    if report.target_peer_id == "server":
        r = get_redis()
        key = f"metrics:{report.peer_id}"
        await r.lpush(key, report.model_dump_json())
        await r.ltrim(key, 0, _MAX_REPORTS - 1)

    # 2. Update Neo4j graph for P2P routing
    driver = get_neo4j()
    query = (
        "MATCH (a:Peer {peer_id: $src_id}), (b:Peer {peer_id: $dst_id}) "
        "MERGE (a)-[r:CONNECTS_TO]->(b) "
        "SET r.rtt_ms = $rtt_ms, "
        "    r.jitter_ms = $jitter_ms, "
        "    r.loss_rate = $loss_rate, "
        "    r.updated_at = datetime() "
        "RETURN r"
    )
    
    # Special case: 'server' node might not exist as a :Peer node, or we can create it.
    # For now, let's assume we only track Peer-to-Peer edges in the graph for routing.
    if report.target_peer_id != "server":
        async with driver.session() as session:
            await session.run(
                query,
                src_id=report.peer_id,
                dst_id=report.target_peer_id,
                rtt_ms=report.rtt_ms,
                jitter_ms=report.jitter_ms,
                loss_rate=report.loss_rate
            )


async def get_average(peer_id: str) -> dict | None:
    r = get_redis()
    key = f"metrics:{peer_id}"
    items_raw = await r.lrange(key, 0, -1)
    if not items_raw:
        return None
    items = [MetricReport.model_validate_json(raw) for raw in items_raw]
    n = len(items)
    return {
        "rtt_ms": sum(item.rtt_ms for item in items) / n,
        "jitter_ms": sum(item.jitter_ms for item in items) / n,
        "loss_rate": sum(item.loss_rate for item in items) / n,
        "samples": n,
    }
