"""Shared A→B→C relay question: state, questions and answer interpretation (CLI + /jev/ask)."""
from __future__ import annotations

DEFAULT_QUESTION = "¿Conviene saltar por {relay} ({source}→{relay}→{target}) en vez de ir directo {source}→{target}?"
DEFAULT_TRUE = "utilizar el relay"
DEFAULT_FALSE = "utilizar la conexión punto a punto."
CONTEXT = "RockDove: transferencia de archivos con Reed-Solomon FEC sobre UDP entre peers."

REDUNDANCY_CRITERIA = [
    "Ninguna (5% overhead)",
    "Rápido (10%)",
    "Balanceado (25%)",
    "Alto (40%)",
    "Máximo (50%)",
]
REDUNDANCY_LEVELS = [0.05, 0.10, 0.25, 0.40, 0.50]


def via_relay(leg1: dict, leg2: dict) -> dict:
    def _sum(key: str):
        a, b = leg1.get(key), leg2.get(key)
        return None if a is None or b is None else round(a + b, 1)

    l1, l2 = leg1.get("loss_rate"), leg2.get("loss_rate")
    loss = None if l1 is None or l2 is None else round(1 - (1 - l1) * (1 - l2), 4)
    return {
        "rtt_ms": _sum("rtt_ms"),
        "jitter_ms": _sum("jitter_ms"),
        "loss_rate": loss,
        "reachable": bool(leg1.get("reachable", True) and leg2.get("reachable", True)),
        "hops": 2,
    }


def build_route_state(source: str, relay: str, target: str, links: dict[str, dict], peers: dict | None = None) -> dict:
    direct = links["direct"]
    state: dict = {
        "topology": {"source": source, "relay": relay, "target": target},
        "links": {
            f"{source}->{target}": direct,
            f"{source}->{relay}": links["source_to_relay"],
            f"{relay}->{target}": links["relay_to_target"],
        },
        "routes": {
            f"direct ({source}->{target})": {**direct, "hops": 1},
            f"via_relay ({source}->{relay}->{target})": via_relay(links["source_to_relay"], links["relay_to_target"]),
        },
        "context": CONTEXT,
    }
    if peers:
        state["peers"] = peers
    return state


def build_questions(question: str, true: str, false: str, *, source: str, relay: str, target: str,
                    redundancy: bool = False) -> dict:
    fmt = {"source": source, "target": target, "relay": relay}
    questions: dict = {
        "decision": {
            "type": "noul",
            "instructions": question.format(**fmt),
            "criteria": {"true": true.format(**fmt), "false": false.format(**fmt)},
        }
    }
    if redundancy:
        questions["redundancy"] = {
            "type": "score",
            "instructions": f"¿Qué grado de redundancia FEC necesita la ruta de {source} a {target}?",
            "criteria": REDUNDANCY_CRITERIA,
        }
    return questions


def interpret(questions: dict, answers: dict, threshold: float) -> dict:
    noul = float(answers.get("decision", {}).get("noul", 0.0))
    verdict = noul >= 0.5
    conf = max(noul, 1.0 - noul)
    crit = questions["decision"]["criteria"]
    out: dict = {
        "verdict": verdict,
        "label": crit["true"] if verdict else crit["false"],
        "p_true": round(noul, 4),
        "confidence": round(conf, 4),
        "threshold": threshold,
        "act": conf >= threshold,
    }
    if "redundancy" in answers:
        rb = answers["redundancy"]
        score = float(rb.get("score", 0.0))
        idx = max(0, min(len(REDUNDANCY_LEVELS) - 1, round(score)))
        out["redundancy"] = {
            "band": REDUNDANCY_CRITERIA[idx],
            "level": REDUNDANCY_LEVELS[idx],
            "score": round(score, 3),
            "confidence": round(float(rb.get("confidence", 0.0)), 4),
        }
    return out
