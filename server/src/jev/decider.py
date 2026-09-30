"""Build Jev state/questions and turn its answers into RockDove decisions.

Design (following TypeSafe's recommended pattern):

* One Jev call evaluates every independent decision in parallel over the same
  ``state``. We ask three typed questions in a single request:
    - ``redundancy_band`` (Score)  → RS redundancy *degree* (gradient).
    - ``should_relay``    (Noul)   → whether to jump through a relay host.
    - ``relay_target``    (Choice) → which relay to use (if any).

* The redundancy + relay questions are *independent* judgments about the same
  metrics, so they belong together in one call rather than one call per metric
  (extra parallel questions add latency-free tokens, not round-trips).

* Results are confidence-gated: act on Jev only above the configured threshold,
  otherwise fall back to the deterministic quality table. This keeps Jev purely
  additive so the current rule-based behaviour is never degraded.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from config import get_settings
from metrics.collector import get_average
from metrics.recommender import compute_recommendation
from redis_client import get_redis

from .client import JevClient, JevError

# Ordered score ladder 0..4 → redundancy level r. Mirrors the RS presets in
# docs/arquitectura_src.md (rapido/balanceado/resiliente) extended with the
# extreme ends of the slider range [0.05, 0.50].
_REDUNDANCY_LADDER: list[tuple[int, float, str]] = [
    (0, 0.05, "Ninguna (5% overhead)"),
    (1, 0.10, "Rápido (10%)"),
    (2, 0.25, "Balanceado (25%)"),
    (3, 0.40, "Alto (40%)"),
    (4, 0.50, "Máximo (50%)"),
]

_RELAY_SCORE_CRITERIA = [desc for _, _, desc in _REDUNDANCY_LADDER]

# Band names returned for the redundancy answer (kept in sync with ladder).
_BAND_TO_LEVEL = {idx: level for idx, level, _ in _REDUNDANCY_LADDER}


@dataclass
class TransitDecision:
    """Final decision RockDove should act on for a source→target transfer."""

    redundancy_level: float
    quality: str
    profile_name: str
    should_relay: bool
    relay_peer_id: str | None
    based_on_samples: int
    source: str | None = None
    target: str | None = None
    evidence: dict = field(default_factory=dict)  # raw Jev answers
    source_name: Literal["jev", "deterministic", "default"] = "deterministic"
    confidence: float | None = None


def _org_id_for(source_id: str, target_id: str) -> str:
    """Resolve the org that owns both peers (dev-mode aware).

    In dev mode (no OIDC) peer keys live under org ``dev``. In OIDC mode the
    org derived from the token should be supplied by the caller; for the plain
    endpoint we default to scanning the dev namespace which is the common case.
    """
    return "dev"


async def _peer_metrics(peer_id: str, org_id: str) -> tuple[dict | None, dict]:
    """Return (avg_metrics, peer_registration) for a peer, or (None, {})."""
    r = get_redis()
    data = await r.hgetall(f"peer:{org_id}:{peer_id}")
    avg = await get_average(peer_id)
    return avg, data


def _fallback(
    avg: dict,
    network_hint: str,
    source: str | None = None,
    target: str | None = None,
) -> TransitDecision:
    """Deterministic path: current quality table, no relay (or forced)."""
    level, quality, profile_name = compute_recommendation(
        rtt_ms=avg["rtt_ms"],
        jitter_ms=avg["jitter_ms"],
        loss_rate=avg["loss_rate"],
        network_hint=network_hint,
    )
    return TransitDecision(
        redundancy_level=level,
        quality=quality,
        profile_name=profile_name,
        should_relay=False,
        relay_peer_id=None,
        based_on_samples=avg["samples"],
        source=source,
        target=target,
        source_name="deterministic",
    )


async def decide_transit(
    source_id: str,
    target_id: str,
    relay_candidates: list[str] | None = None,
    *,
    force_jev: bool = False,
) -> TransitDecision:
    """Compute redundancy degree + relay/jump decision for a source→target hop.

    If Jev is available it makes the whole decision in one parallel call;
    otherwise (disabled / missing key / low confidence) it falls back to the
    deterministic quality table for redundancy and no relay.
    """
    org_id = _org_id_for(source_id, target_id)

    src_avg, src_peer = await _peer_metrics(source_id, org_id)
    tgt_avg, tgt_peer = await _peer_metrics(target_id, org_id)
    samples = (src_avg or {}).get("samples", 0) + (tgt_avg or {}).get("samples", 0)

    if not src_avg and not tgt_avg:
        # No telemetry at all → conservative deterministic default.
        level, quality, profile_name = compute_recommendation(
            rtt_ms=0.0, jitter_ms=0.0, loss_rate=0.0,
            network_hint="auto",
        )
        return TransitDecision(
            redundancy_level=level, quality=quality, profile_name=profile_name,
            should_relay=False, relay_peer_id=None, based_on_samples=0,
            source=source_id, target=target_id,
        )

    # Build the effective link metrics combining both endpoints (the strongest
    # signal from both ends guards the transfer in one direction).
    def _pick_avg(avg: dict | None, hint_default: float) -> float:
        return avg[hint_default] if avg else hint_default

    eff_rtt = max(_pick_avg(src_avg, "rtt_ms"), _pick_avg(tgt_avg, "rtt_ms"))
    eff_jit = max(_pick_avg(src_avg, "jitter_ms"), _pick_avg(tgt_avg, "jitter_ms"))
    eff_loss = max(_pick_avg(src_avg, "loss_rate"), _pick_avg(tgt_avg, "loss_rate"))
    eff_hint = src_peer.get("network_hint", "auto") or "auto"

    settings = get_settings()
    client = JevClient()

    if (settings.JEV_ENABLED or force_jev) and client.enabled:
        try:
            dec = await _decide_with_jev(
                client, source_id, target_id, relay_candidates or [],
                rtt_ms=eff_rtt, jitter_ms=eff_jit, loss_rate=eff_loss,
                hint=eff_hint, samples=samples,
            )
            return dec
        except JevError as exc:  # network / auth / missing key
            # Degrade gracefully: keep serving with the rule-based table.
            log = logging.getLogger("jev")
            log.warning(
                "Jev unavailable, falling back to deterministic table: %s", exc
            )
    # Jev disabled → deterministic only.
    return _fallback(
        {"rtt_ms": eff_rtt, "jitter_ms": eff_jit, "loss_rate": eff_loss,
         "samples": samples},
        eff_hint,
        source=source_id, target=target_id,
    )


async def _decide_with_jev(
    client: JevClient,
    source_id: str,
    target_id: str,
    relay_candidates: list[str],
    *,
    rtt_ms: float,
    jitter_ms: float,
    loss_rate: float,
    hint: str,
    samples: int,
) -> TransitDecision:
    from metrics.recommender import PROFILES

    profile_label = PROFILES.get(hint, {}).get("label", "auto")

    state = {
        "link": {
            "rtt_ms": round(rtt_ms, 1),
            "jitter_ms": round(jitter_ms, 1),
            "loss_rate": round(loss_rate, 4),
            "network_hint": hint,
            "network_profile": profile_label,
            "telemetry_samples": samples,
        },
        "topology": {
            "source_peer": source_id,
            "target_peer": target_id,
            "relay_candidates": relay_candidates,
        },
        "task": (
            "Decide the Reed-Solomon redundancy degree and whether to jump "
            "through an intermediate relay host to reach the target peer."
        ),
    }

    questions: dict = {
        "redundancy_band": {
            "type": "score",
            "instructions": (
                "Choose the redundancy degree (FEC overhead) needed to make "
                "the transfer reliable given the link quality metrics."
            ),
            "criteria": _RELAY_SCORE_CRITERIA,
        },
        "should_relay": {
            "type": "noul",
            "instructions": (
                "Should the source jump through an intermediate relay host "
                "instead of sending directly to the target?"
            ),
            "criteria": {
                "true": (
                    "The direct path is unreliable or unavailable, a relay "
                    "would improve reachability or reliability."
                ),
                "false": (
                    "The direct path between source and target is usable and "
                    "a relay adds no benefit."
                ),
            },
        },
    }

    # Only ask the relay Choice when there is at least one candidate, and only
    # give the "direct" option as a first-class alternative so Jev can choose
    # not to use any relay.
    candidates = relay_candidates or []
    if candidates:
        options = {"direct": "Send directly to the target peer, no relay."}
        for c in candidates:
            options[c] = f"Route the transfer through relay peer '{c}'."
        questions["relay_target"] = {
            "type": "choice",
            "instructions": (
                "Which relay host should carry the transfer, if any? "
                "'direct' means no relay."
            ),
            "criteria": options,
        }

    answers = await client.decide(state, questions)

    # ── Parse redundancy (Score) ──────────────────────────────────────────────
    threshold = get_settings().JEV_CONFIDENCE_THRESHOLD
    rb = answers.get("redundancy_band", {})
    score = float(rb.get("score", 1.0))
    conf = float(rb.get("confidence", 0.0))
    idx = max(0, min(len(_REDUNDANCY_LADDER) - 1, int(round(score))))
    redundancy_level = _BAND_TO_LEVEL[idx]
    quality = _band_quality(idx)

    # ── Parse relay (Noul) ────────────────────────────────────────────────────
    sr = answers.get("should_relay", {})
    noul_prob = float(sr.get("noul", 0.0))
    noul_conf = max(noul_prob, 1.0 - noul_prob)
    should_relay = bool(noul_prob >= 0.5)

    # If confidence on the *redundancy* is too low, fall back to the rule table
    # for the level (but still use Jev for the relay signal, which is separate).
    source_name: Literal["jev", "deterministic", "default"] = "jev"
    if conf < threshold:
        fallback = _fallback(
            {"rtt_ms": rtt_ms, "jitter_ms": jitter_ms, "loss_rate": loss_rate,
             "samples": samples},
            hint,
            source=source_id, target=target_id,
        )
        redundancy_level = fallback.redundancy_level
        quality = fallback.quality
        source_name = "deterministic"

    # ── Parse relay target (Choice) ───────────────────────────────────────────
    relay_peer_id: str | None = None
    if candidates:
        rt = answers.get("relay_target", {})
        choice = rt.get("choice")
        if should_relay and choice and choice != "direct":
            relay_peer_id = choice

    # Keep the deterministic profile label for consistency where possible.
    from metrics.recommender import _QUALITY_TO_PROFILE_LABEL
    profile_name = _QUALITY_TO_PROFILE_LABEL.get(quality, profile_label)

    return TransitDecision(
        redundancy_level=redundancy_level,
        quality=quality,
        profile_name=profile_name,
        should_relay=should_relay,
        relay_peer_id=relay_peer_id,
        based_on_samples=samples,
        source=source_id,
        target=target_id,
        evidence={
            "answers": answers,
            "redundancy_confidence": round(conf, 4),
            "noul_confidence": round(noul_conf, 4),
        },
        source_name=source_name,
        confidence=round(conf, 4),
    )


def _band_quality(idx: int) -> str:
    q = ["excellent", "good", "good", "poor", "critical"]
    return q[max(0, min(len(q) - 1, idx))]