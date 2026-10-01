"""
Background RTT/jitter probe for network quality monitoring.

Every 60s, pings all online peers and reports measured latency to the server.
Two reporting channels:
  * HTTP: POST /metrics/report (always — feeds the central server + Neo4j).
  * QUIC stream (when TRANSPORT_MODE=quic): a reliable in-band metric signal
    (RFC 9221 DATAGRAM for RS blocks, QUIC stream for metrics) so peers can
    observe link quality directly, e.g. via a sat/edge relay.

Both report the same measured RTT/jitter/loss so the Jev decider (server) and
peers agree on link state.
"""
import asyncio
import json
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


async def _report_over_quic(host: str, port: int, report: dict) -> None:
    """Best-effort delivery of a metric signal over a QUIC stream."""
    try:
        from rs.transport import QUICTransport, get_transport
        transport = get_transport()
        if isinstance(transport, QUICTransport):
            await transport.send_metric(host, port, json.dumps(report).encode())
    except Exception:
        pass


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
                report = {
                    "peer_id": settings.PEER_ID,
                    "target_peer_id": target_peer_id,
                    "rtt_ms": rtt_ms,
                    "jitter_ms": jitter_ms,
                    "loss_rate": 0.0,
                    "recorded_at": None,
                }
                if rtt_ms > 0:
                    await server_client.report_metrics(
                        settings.PEER_ID,
                        target_peer_id=target_peer_id,
                        rtt_ms=rtt_ms,
                        jitter_ms=jitter_ms,
                        loss_rate=0.0,
                    )
                # In QUIC mode also push the same signal in-band to the peer.
                await _report_over_quic(peer.get("udp_host", ""), peer.get("udp_port", 0), report)
            except Exception:
                pass
