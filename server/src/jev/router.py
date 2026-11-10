"""HTTP API for Jev decision-making on RockDove transit links.

Endpoints
---------
GET  /jev/status                       whether Jev is available + model
GET  /jev/transit/{source}/{target}    redundancy degree + relay decision
                                       for a source→target transfer (one Jev call).
POST /jev/mock/seed                    seed mock metrics between two hosts.
POST /jev/mock/seed/{scenario}         seed a named scenario.
GET  /jev/ui                           HTML page: pick live peers A/B/C and ask Jev.
GET  /jev/peers                        live peers (alive status) for the UI.
GET  /jev/links                        live A–C, A–B, B–C link metrics + history.
POST /jev/populate                     micro-transfers between real peers (feeds Neo4j/Redis).
POST /jev/ask                          ask the A→B→C relay question (+ redundancy).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from auth.deps import CallerInfo, extract_auth
from config import get_settings

from . import live
from . import mock as mock_mod
from .ask import DEFAULT_FALSE, DEFAULT_QUESTION, DEFAULT_TRUE, build_questions, build_route_state, interpret
from .client import JevClient, JevError
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

_UI_HTML = Path(__file__).parent / "static" / "ask.html"


class LinkIn(BaseModel):
    rtt_ms: float | None = Field(default=None, ge=0)
    jitter_ms: float | None = Field(default=None, ge=0)
    loss_rate: float | None = Field(default=None, ge=0, le=1)
    reachable: bool = True
    origin: str | None = None


class AskRequest(BaseModel):
    source: str
    relay: str
    target: str
    question: str = DEFAULT_QUESTION
    true: str = DEFAULT_TRUE
    false: str = DEFAULT_FALSE
    threshold: float | None = Field(default=None, ge=0, le=1)
    redundancy: bool = True
    links: dict[str, LinkIn] | None = None  # keys: direct, source_to_relay, relay_to_target
    dry_run: bool = False


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def ui() -> HTMLResponse:
    return HTMLResponse(_UI_HTML.read_text(encoding="utf-8"))


@router.get("/peers")
async def live_peers(caller: CallerInfo = Depends(extract_auth)) -> dict:
    peers, origin = await live.list_peers(caller)
    peers.sort(key=lambda p: (not p.get("online"), p["peer_id"]))
    return {"peers": peers, "origin": origin, "timeout_s": get_settings().HEARTBEAT_TIMEOUT_S}


@router.get("/links")
async def live_links(source: str, relay: str, target: str, caller: CallerInfo = Depends(extract_auth)) -> dict:
    links, status, history = await live.route_links(source, relay, target, caller)
    return {"links": links, "peers": status, "history": history}


@router.post("/ask")
async def ask(req: AskRequest, caller: CallerInfo = Depends(extract_auth)) -> dict:
    if len({req.source, req.relay, req.target}) != 3:
        raise HTTPException(400, "source, relay y target tienen que ser peers distintos")
    links_live, status, _ = await live.route_links(req.source, req.relay, req.target, caller)
    links = {k: v.model_dump() for k, v in req.links.items()} if req.links else links_live
    missing = {"direct", "source_to_relay", "relay_to_target"} - links.keys()
    if missing:
        raise HTTPException(400, f"faltan enlaces: {sorted(missing)}")
    state = build_route_state(req.source, req.relay, req.target, links, peers=status)
    questions = build_questions(req.question, req.true, req.false, source=req.source, relay=req.relay,
                                target=req.target, redundancy=req.redundancy)
    settings = get_settings()
    threshold = req.threshold if req.threshold is not None else settings.JEV_CONFIDENCE_THRESHOLD
    if req.dry_run:
        return {"state": state, "questions": questions, "model": settings.JEV_MODEL}
    try:
        answers = await JevClient().decide(state, questions, force=True)
    except JevError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"state": state, "questions": questions, "answers": answers,
            "result": interpret(questions, answers, threshold)}


class PopulateRequest(BaseModel):
    peers: list[str] = Field(min_length=2, max_length=5)
    rounds: int = Field(default=3, ge=1, le=10)
    size_kb: int = Field(default=4, ge=1, le=256)
    redundancy: float = Field(default=0.25, ge=0.05, le=0.50)


@router.post("/populate")
async def populate(req: PopulateRequest, caller: CallerInfo = Depends(extract_auth)) -> dict:
    if get_settings().OIDC_ENABLED and not caller.is_admin:
        raise HTTPException(403, "solo admin")
    if len(set(req.peers)) != len(req.peers):
        raise HTTPException(400, "peers repetidos")
    try:
        results = await live.populate(req.peers, caller, rounds=req.rounds, size_kb=req.size_kb,
                                      redundancy=req.redundancy)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ok = sum(1 for r in results if r.get("status") in ("ok", "degraded"))
    return {"transfers": results, "ok": ok, "total": len(results)}
