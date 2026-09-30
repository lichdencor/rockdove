"""HTTP API for Jev decision-making on RockDove transit links.

Endpoints
---------
GET  /jev/status                       whether Jev is available + model
GET  /jev/transit/{source}/{target}    redundancy degree + relay decision
                                       for a source→target transfer (one Jev call).
POST /jev/mock/seed                    seed mock metrics between two hosts.
POST /jev/mock/seed/{scenario}         seed a named scenario.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from config import get_settings

from . import mock as mock_mod
from .client import JevClient
from .decider import TransitDecision, decide_transit

router = APIRouter()


@router.get("/status")
async def status() -> dict:
    settings = get_settings()
    client = JevClient()
    return {
        "jev_enabled": bool(settings.JEV_ENABLED),
        "configured": bool(settings.OPENROUTER_API_KEY),
        "model": settings.JEV_MODEL,
        "confidence_threshold": settings.JEV_CONFIDENCE_THRESHOLD,
        "ready": client.enabled,
    }


@router.get("/transit/{source}/{target}", response_model=TransitDecision)
async def get_transit_decision(
    source: str,
    target: str,
    relay: list[str] = Query(
        default=[], description="Candidate relay peer IDs to consider"
    ),
    preview: bool = Query(
        default=False,
        description="If true, always ask Jev even when JEV_ENABLED=false (dev).",
    ),
) -> TransitDecision:
    candidates = [c for c in relay if c]
    try:
        return await decide_transit(source, target, candidates, force_jev=preview)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"decision failed: {exc}") from exc


@router.post("/mock/seed")
@router.post("/mock/seed/{scenario}")
async def seed_mock(
    scenario: str = "satellite",
    samples: int = Query(default=8, ge=1, le=50),
) -> dict:
    """Seed mock metrics between two hosts and return the Jev decision.

    Calling the auto-decided transit decision lets you see immediately how Jev
    would route a transfer on those mocked links.
    """
    try:
        seeded = await mock_mod.seed_scenario(scenario, samples=samples)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    hosts = seeded["hosts"]
    try:
        dec = await decide_transit(
            hosts[0], hosts[1], seeded["relay_candidates"], force_jev=False
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"decision failed: {exc}") from exc

    return {
        "seeded": seeded,
        "decision": dec,
    }