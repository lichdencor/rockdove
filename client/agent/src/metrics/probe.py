"""
Background RTT/jitter probe for network quality monitoring.

Every 60s, pings all online peers via HTTP /health and reports measured
latency to the server. This feeds the adaptive redundancy recommender with
real network data so it can make meaningful recommendations.
"""
import asyncio
import time

import httpx

from config import get_settings
from server_client import server_client

_INTERVAL_S = 60
_PING_COUNT = 5
_PING_DELAY_S = 0.1


async def _probe_rtt(api_url: str) -> tuple[float, float]:
    """HTTP RTT probe to a peer. Returns (mean_rtt_ms, jitter_ms)."""
    samples: list[float] = []
    async with httpx.AsyncClient(timeout=3.0) as client:
        for _ in range(_PING_COUNT):
            t0 = time.monotonic()
            try:
                await client.get(f"{api_url}/health")
                samples.append((time.monotonic() - t0) * 1000.0)
            except Exception:
                pass
            await asyncio.sleep(_PING_DELAY_S)
    if not samples:
        return 0.0, 0.0
    mean = sum(samples) / len(samples)
    jitter = sum(abs(s - mean) for s in samples) / len(samples)
    return mean, jitter


async def rtt_probe_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(_INTERVAL_S)
        try:
            peers = await server_client.get_peers()
        except Exception:
            continue
        for peer in peers:
            if peer.get("peer_id") == settings.PEER_ID:
                continue
            if not peer.get("online"):
                continue
            api_url = peer.get("api_url", "")
            target_peer_id = peer.get("peer_id")
            if not api_url or not target_peer_id:
                continue
            try:
                rtt_ms, jitter_ms = await _probe_rtt(api_url)
                if rtt_ms > 0:
                    await server_client.report_metrics(
                        settings.PEER_ID,
                        target_peer_id=target_peer_id,
                        rtt_ms=rtt_ms,
                        jitter_ms=jitter_ms,
                        loss_rate=0.0,
                    )
            except Exception:
                pass
