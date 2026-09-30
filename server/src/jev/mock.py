"""Seed mocked telemetry between two hosts into Redis.

This lets you exercise the full Jev decision pipeline end-to-end without
real agents: it registers two peers (plus optional relays) and injects a batch
of ``MetricReport`` samples. Used by ``POST /jev/mock/seed``.

Host profiles model real RockDove scenarios (see docs/NETWORK_INFRA.md):

  * ``satellite`` — high RTT / jitter / loss → Jev should pick max redundancy
                    and likely recommend jumping through a relay.
  * ``lan``       — clean low-latency link → minimal redundancy, direct.
"""
from __future__ import annotations

import httpx

from config import get_settings
from metrics.collector import store_report
from metrics.models import MetricReport
from redis_client import get_redis

ORG_ID = "dev"


# host name → (rtt_ms, jitter_ms, loss_rate, network_hint, group)
SCENARIOS: dict[str, list[tuple[str, float, float, float, str, str]]] = {
    # (host, rtt_ms, jitter_ms, loss_rate, network_hint, profile_label)
    "satellite": [
        ("edge-hq",      420.0,  95.0, 0.32, "satellite", "Satellite"),
        ("edge-remote",  480.0, 120.0, 0.38, "satellite", "Satellite"),
    ],
    "lan": [
        ("peer-alice",   12.0,  1.5, 0.001, "lan", "LAN"),
        ("peer-bob",      9.0,  2.0, 0.002, "lan", "LAN"),
    ],
    "wifi": [
        ("hs-wifi-a",    45.0,  9.0, 0.04, "wifi", "Wi-Fi"),
        ("hs-wifi-b",    60.0, 13.0, 0.06, "wifi", "Wi-Fi"),
    ],
}

RELAY_CANDIDATES = ["relay-core"]


async def _register_peer(peer_id: str, network_hint: str) -> None:
    r = get_redis()
    key = f"peer:{ORG_ID}:{peer_id}"
    await r.hset(key, mapping={
        "peer_id": peer_id,
        "api_url": f"http://mock-{peer_id}:8000",
        "udp_host": f"10.0.0.{abs(hash(peer_id)) % 200 + 1}",
        "udp_port": "9001",
        "last_seen": "2026-01-01T00:00:00+00:00",
        "network_hint": network_hint,
        "group": "default",
        "org_id": ORG_ID,
    })
    await r.expire(key, 3600)


async def seed_scenario(scenario: str = "satellite", samples: int = 8) -> dict:
    """Seed metrics + registrations for the two hosts of a scenario.

    Optionally registers the relay candidate too so the relay Choice question
    has something to pick from.
    """
    if scenario not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario '{scenario}'; choose from {list(SCENARIOS)}"
        )

    hosts = SCENARIOS[scenario]
    peers: list[str] = []

    for peer_id, rtt, jit, loss, hint, _label in hosts:
        peers.append(peer_id)
        await _register_peer(peer_id, hint)
        for _ in range(samples):
            await store_report(MetricReport(
                peer_id=peer_id,
                rtt_ms=rtt,
                jitter_ms=jit,
                loss_rate=loss,
                bandwidth_mbps=50.0,
            ))

    for relay_id in RELAY_CANDIDATES:
        await _register_peer(relay_id, "lan")

    return {
        "scenario": scenario,
        "hosts": [h[0] for h in hosts],
        "relay_candidates": list(RELAY_CANDIDATES),
        "samples_per_host": samples,
        "org_id": ORG_ID,
    }