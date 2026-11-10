from fastapi import APIRouter, Depends, HTTPException
from auth.deps import CallerInfo, extract_auth
from neo4j_client import get_neo4j
from pydantic import BaseModel

router = APIRouter()

class RouteResponse(BaseModel):
    source_id: str
    target_id: str
    path: list[str]
    total_rtt_ms: float
    hops: int

@router.get("/route", response_model=RouteResponse)
async def get_route(
    target_id: str,
    source_id: str | None = None,
    caller: CallerInfo = Depends(extract_auth),
) -> RouteResponse:
    driver = get_neo4j()
    # If source_id is not provided, use the caller's peer_id (if available)
    actual_source_id = source_id or caller.peer_id
    
    if not actual_source_id:
        raise HTTPException(400, "source_id or authenticated peer_id required")

    # Cypher query to find the shortest path based on RTT
    # We use Dijkstra-like approach via gds or simple shortestPath if GDS is not available.
    # For simplicity, we'll use a path finding query that minimizes the sum of rtt_ms.
    query = (
        "MATCH (start:Peer {peer_id: $src_id, org_id: $org_id}), "
        "      (end:Peer {peer_id: $dst_id, org_id: $org_id}) "
        "MATCH p = shortestPath((start)-[:CONNECTS_TO*..5]->(end)) "
        "RETURN [n in nodes(p) | n.peer_id] as path, "
        "       reduce(s = 0.0, r in relationships(p) | s + r.rtt_ms) as total_rtt"
    )

    async with driver.session() as session:
        result = await session.run(
            query, 
            src_id=actual_source_id, 
            dst_id=target_id, 
            org_id=caller.org_id
        )
        record = await result.single()
        
        if not record:
            # Fallback: check if both peers exist
            check_query = "MATCH (p:Peer {peer_id: $id, org_id: $org_id}) RETURN p"
            src_exists = await (await session.run(check_query, id=actual_source_id, org_id=caller.org_id)).single()
            dst_exists = await (await session.run(check_query, id=target_id, org_id=caller.org_id)).single()
            
            if not src_exists:
                raise HTTPException(404, f"Source peer {actual_source_id} not found")
            if not dst_exists:
                raise HTTPException(404, f"Target peer {target_id} not found")
            
            raise HTTPException(404, "No path found between peers")

        path = record["path"]
        total_rtt = record["total_rtt"]
        
        return RouteResponse(
            source_id=actual_source_id,
            target_id=target_id,
            path=path,
            total_rtt_ms=total_rtt,
            hops=len(path) - 1
        )
