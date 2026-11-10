#!/usr/bin/env python3
"""Probe if Jev really decides based on link metrics, or answers randomly.

For each scenario (different RTT/jitter/loss seeded into the server) it queries
/jev/transit N times and records the decisions + raw Jev probabilities. Then
prints a comparison so we can judge correlation (decides) vs chaos (random).

Usage:
  python3 scripts/probe_jev_decision.py [server_url]
  default server_url: http://100.101.120.123:8090
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://100.101.120.123:8090"
ROUNDS = 3  # queries per scenario

# scenario -> the two hosts seeded by /jev/mock/seed/{scenario}
SCENARIOS = {
    "lan":       ("peer-alice", "peer-bob"),
    "wifi":      ("hs-wifi-a",  "hs-wifi-b"),
    "satellite": ("edge-hq",    "edge-remote"),
}


def req(method, url, body=None):
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    summary = {}
    for scenario, (a, b) in SCENARIOS.items():
        # Seed the scenario so the server has fresh link metrics.
        req("POST", f"{BASE}/jev/mock/seed/{scenario}?samples=6")
        time.sleep(1)
        results = []
        for i in range(ROUNDS):
            dec = req("GET", f"{BASE}/jev/transit/{a}/{b}?relay=relay-core")
            evidence = dec.get("evidence", {})
            answers = evidence.get("answers", {})
            redundancy_raw = answers.get("redundancy_band", {})
            relay_raw = answers.get("should_relay", {})
            row = {
                "round": i + 1,
                "redundancy_level": dec.get("redundancy_level"),
                "quality": dec.get("quality"),
                "should_relay": dec.get("should_relay"),
                "relay_peer": dec.get("relay_peer_id"),
                "source_name": dec.get("source_name"),
                "conf": dec.get("confidence"),
                # raw Jev internals
                "jev_redundancy_band": redundancy_raw.get("score"),
                "jev_band_prob": redundancy_raw.get("probabilities"),
                "jev_should_relay_noul": relay_raw.get("noul"),
            }
            results.append(row)
            time.sleep(0.7)
        summary[scenario] = results

    # ── Print a compact comparison ─────────────────────────────────────────
    print(f"\nJev probe vs {BASE} — {ROUNDS} rounds per scenario\n")
    hdr = f"{'scenario':<10} {'round':<6} {'out_level':<10} {'out_quality':<10} {'out_relay':<9} {'src':<10} {'jev_band':<9} {'noul(relay)':<11}"
    print(hdr)
    print("-" * len(hdr))
    for scenario, rows in summary.items():
        for row in rows:
            print(
                f"{scenario:<10} {row['round']:<6} "
                f"{row['redundancy_level']:<10} {row['quality']:<10} "
                f"{row['should_relay']:<9} {row['source_name']:<10} "
                f"{row['jev_redundancy_band']:<9} {row['jev_should_relay_noul']:<11}"
            )

    print("\n=== Análisis ===\n")
    for scenario, rows in summary.items():
        levels = {r["redundancy_level"] for r in rows}
        confs = [r["conf"] for r in rows]
        bands = [r["jev_redundancy_band"] for r in rows]
        stable = "ESTABLE" if len(levels) == 1 else f"VARÍA {sorted(levels)}"
        conf_txt = ",".join(f"{c:.2f}" if c is not None else "?" for c in confs)
        print(f"- {scenario:>10}: nivel_out={stable}, bandas_jev={sorted({b for b in bands if b is not None})}, conf={conf_txt}")


if __name__ == "__main__":
    main()