"""CLI to ask Jev ad-hoc questions over mocked RockDove link metrics (see docs/JEV.md)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from config import get_settings
from jev.ask import (DEFAULT_FALSE, DEFAULT_QUESTION, DEFAULT_TRUE, build_questions,
                     build_route_state, interpret)
from jev.client import JevClient, JevError

# scenario → link metrics for direct (source→target) and the two relay legs
SCENARIOS: dict[str, dict[str, dict]] = {
    "degraded": {
        "direct": {"rtt_ms": 480.0, "jitter_ms": 110.0, "loss_rate": 0.30, "reachable": True},
        "source_to_relay": {"rtt_ms": 35.0, "jitter_ms": 4.0, "loss_rate": 0.01, "reachable": True},
        "relay_to_target": {"rtt_ms": 40.0, "jitter_ms": 5.0, "loss_rate": 0.01, "reachable": True},
    },
    "healthy": {
        "direct": {"rtt_ms": 18.0, "jitter_ms": 2.0, "loss_rate": 0.002, "reachable": True},
        "source_to_relay": {"rtt_ms": 30.0, "jitter_ms": 3.0, "loss_rate": 0.005, "reachable": True},
        "relay_to_target": {"rtt_ms": 32.0, "jitter_ms": 3.0, "loss_rate": 0.005, "reachable": True},
    },
    "nat-blocked": {
        "direct": {"rtt_ms": None, "jitter_ms": None, "loss_rate": 1.0, "reachable": False},
        "source_to_relay": {"rtt_ms": 25.0, "jitter_ms": 3.0, "loss_rate": 0.01, "reachable": True},
        "relay_to_target": {"rtt_ms": 28.0, "jitter_ms": 3.0, "loss_rate": 0.01, "reachable": True},
    },
    "relay-worse": {
        "direct": {"rtt_ms": 90.0, "jitter_ms": 12.0, "loss_rate": 0.04, "reachable": True},
        "source_to_relay": {"rtt_ms": 220.0, "jitter_ms": 60.0, "loss_rate": 0.12, "reachable": True},
        "relay_to_target": {"rtt_ms": 250.0, "jitter_ms": 70.0, "loss_rate": 0.15, "reachable": True},
    },
}

def build_state(args: argparse.Namespace) -> dict:
    if args.state_file:
        with open(args.state_file, encoding="utf-8") as fh:
            return json.load(fh)
    links = json.loads(json.dumps(SCENARIOS[args.scenario]))
    direct = links["direct"]
    for key, val in (("rtt_ms", args.rtt), ("jitter_ms", args.jitter), ("loss_rate", args.loss)):
        if val is not None:
            direct[key] = val
    return build_route_state(args.source, args.relay, args.target, links)


def _fmt_link(m: dict) -> str:
    if not m.get("reachable", True):
        return "caído"
    return f"rtt={m.get('rtt_ms')}ms  jitter={m.get('jitter_ms')}ms  loss={float(m.get('loss_rate') or 0):.2%}"


def render(args: argparse.Namespace, state: dict, questions: dict, answers: dict, threshold: float) -> str:
    res = interpret(questions, answers, threshold)
    lines = [
        f"Pregunta : {questions['decision']['instructions']}",
        f"Estado   : {'escenario ' + args.scenario if not args.state_file else 'state-file'}",
    ]
    for name, m in (state.get("routes") or state.get("links") or {}).items():
        lines.append(f"  {name:<34} {_fmt_link(m)}")
    lines += [
        "",
        f"Jev  →  {res['verdict']}  ({res['label']})",
        f"P(true) = {res['p_true']:.3f}   confianza = {res['confidence']:.3f}   umbral = {threshold:.2f}",
        "Gate: " + ("ACTUAR con la respuesta de Jev" if res["act"] else "confianza baja → usar fallback determinista"),
    ]
    if rb := res.get("redundancy"):
        lines += [
            "",
            f"Redundancia → {rb['band']}  (r={rb['level']})",
            f"score = {rb['score']:.2f}   confianza = {rb['confidence']:.3f}",
        ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="jev", description="Consultar a Jev (TypeSafe vía OpenRouter) sobre decisiones de ruteo de RockDove.",
    )
    p.add_argument("--source", default="team-a", help="peer origen (default: team-a)")
    p.add_argument("--target", default="team-c", help="peer destino (default: team-c)")
    p.add_argument("--relay", default="team-b", help="host relay candidato (default: team-b)")
    p.add_argument("-q", "--question", default=DEFAULT_QUESTION, help="pregunta noul; admite {source} {target} {relay}")
    p.add_argument("--true", default=DEFAULT_TRUE, help="criterio para True")
    p.add_argument("--false", default=DEFAULT_FALSE, help="criterio para False")
    p.add_argument("-s", "--scenario", default="degraded", choices=sorted(SCENARIOS), help="métricas mock (default: degraded)")
    p.add_argument("--rtt", type=float, help="override RTT ms del enlace directo")
    p.add_argument("--jitter", type=float, help="override jitter ms del enlace directo")
    p.add_argument("--loss", type=float, help="override loss rate (0-1) del enlace directo")
    p.add_argument("--state-file", help="JSON con un state propio (reemplaza el mock)")
    p.add_argument("-r", "--redundancy", action="store_true", help="preguntar también el grado de redundancia (score)")
    p.add_argument("--threshold", type=float, help="umbral de confianza (default: JEV_CONFIDENCE_THRESHOLD)")
    p.add_argument("--dry-run", action="store_true", help="mostrar el payload sin llamar a Jev")
    p.add_argument("--json", action="store_true", help="imprimir la respuesta cruda en JSON")
    return p.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    state = build_state(args)
    questions = build_questions(args.question, args.true, args.false, source=args.source,
                                relay=args.relay, target=args.target, redundancy=args.redundancy)
    if args.dry_run:
        print(json.dumps({"model": settings.JEV_MODEL, "state": state, "questions": questions},
                         indent=2, ensure_ascii=False))
        return 0
    client = JevClient()
    if not client.configured:
        print("error: OPENROUTER_API_KEY no está definido (env o server/.env)", file=sys.stderr)
        return 2
    try:
        answers = await client.decide(state, questions, force=True)
    except JevError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"state": state, "questions": questions, "answers": answers}, indent=2, ensure_ascii=False))
    else:
        threshold = args.threshold if args.threshold is not None else settings.JEV_CONFIDENCE_THRESHOLD
        print(render(args, state, questions, answers, threshold))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
