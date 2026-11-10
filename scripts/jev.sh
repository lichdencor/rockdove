#!/usr/bin/env bash
# Ask Jev (TypeSafe via OpenRouter) whether to hop A→B→C or go direct A→C; see docs/JEV.md.
#
# Editá el bloque CONFIG y corré ./scripts/jev.sh sin argumentos.
# Args extra se pasan al CLI y pisan la config (ej: --threshold 0.7, -s healthy, --json, --dry-run).
# Key: OPENROUTER_API_KEY en el entorno o en server/.env
set -euo pipefail

# ─────────────────────────────── CONFIG ───────────────────────────────
HOST_A="team-a"        # origen
HOST_B="team-b"        # relay
HOST_C="team-c"        # destino

# enlaces: RTT ms, jitter ms, loss (0-1), alcanzable (true/false)
A_C_RTT=480;  A_C_JITTER=110; A_C_LOSS=0.30; A_C_UP=true
A_B_RTT=35;   A_B_JITTER=4;   A_B_LOSS=0.01; A_B_UP=true
B_C_RTT=40;   B_C_JITTER=5;   B_C_LOSS=0.01; B_C_UP=true

QUESTION="¿Conviene saltar por {relay} ({source}→{relay}→{target}) en vez de ir directo {source}→{target}?"
CRIT_TRUE="utilizar el relay"
CRIT_FALSE="utilizar la conexión punto a punto."

THRESHOLD=0.85         # confianza mínima para actuar con la respuesta de Jev
ASK_REDUNDANCY=true    # además pedir el grado de redundancia (score) en la misma llamada
CONTEXT="RockDove: transferencia de archivos con Reed-Solomon FEC sobre UDP entre peers."
# ──────────────────────────────────────────────────────────────────────

SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../server" && pwd)"

if [[ -f "$SERVER_DIR/.env" && -z "${OPENROUTER_API_KEY:-}" ]]; then
  set -a; source "$SERVER_DIR/.env"; set +a
fi

if [[ -x "$SERVER_DIR/.venv/bin/python" ]]; then
  PY=("$SERVER_DIR/.venv/bin/python")
elif command -v uv >/dev/null 2>&1; then
  PY=(uv run --quiet --project "$SERVER_DIR" python)
else
  echo "error: no hay server/.venv ni uv; corré 'cd server && uv sync'" >&2
  exit 1
fi
export PYTHONPATH="$SERVER_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# si pasás un escenario/estado/override propio, no se usa el estado de CONFIG
USE_CONFIG_STATE=true
for arg in "$@"; do
  case "$arg" in -s|--scenario|--scenario=*|--state-file|--state-file=*|--rtt|--jitter|--loss) USE_CONFIG_STATE=false ;; esac
done

STATE_FILE="$(mktemp --suffix=.json)"
trap 'rm -f "$STATE_FILE"' EXIT

# ruta vía relay: RTT y jitter se suman, la pérdida se compone 1-(1-l1)(1-l2)
VIA_RTT=$(awk -v a="$A_B_RTT" -v b="$B_C_RTT" 'BEGIN{print a+b}')
VIA_JITTER=$(awk -v a="$A_B_JITTER" -v b="$B_C_JITTER" 'BEGIN{print a+b}')
VIA_LOSS=$(awk -v a="$A_B_LOSS" -v b="$B_C_LOSS" 'BEGIN{printf "%.4f", 1-(1-a)*(1-b)}')
VIA_UP=$([[ "$A_B_UP" == true && "$B_C_UP" == true ]] && echo true || echo false)

cat > "$STATE_FILE" <<JSON
{
  "topology": {"source": "$HOST_A", "relay": "$HOST_B", "target": "$HOST_C"},
  "links": {
    "$HOST_A->$HOST_C": {"rtt_ms": $A_C_RTT, "jitter_ms": $A_C_JITTER, "loss_rate": $A_C_LOSS, "reachable": $A_C_UP},
    "$HOST_A->$HOST_B": {"rtt_ms": $A_B_RTT, "jitter_ms": $A_B_JITTER, "loss_rate": $A_B_LOSS, "reachable": $A_B_UP},
    "$HOST_B->$HOST_C": {"rtt_ms": $B_C_RTT, "jitter_ms": $B_C_JITTER, "loss_rate": $B_C_LOSS, "reachable": $B_C_UP}
  },
  "routes": {
    "direct ($HOST_A->$HOST_C)": {"rtt_ms": $A_C_RTT, "jitter_ms": $A_C_JITTER, "loss_rate": $A_C_LOSS, "reachable": $A_C_UP, "hops": 1},
    "via_relay ($HOST_A->$HOST_B->$HOST_C)": {"rtt_ms": $VIA_RTT, "jitter_ms": $VIA_JITTER, "loss_rate": $VIA_LOSS, "reachable": $VIA_UP, "hops": 2}
  },
  "context": "$CONTEXT"
}
JSON

ARGS=(--source "$HOST_A" --relay "$HOST_B" --target "$HOST_C"
      -q "$QUESTION" --true "$CRIT_TRUE" --false "$CRIT_FALSE" --threshold "$THRESHOLD")
[[ "$USE_CONFIG_STATE" == true ]] && ARGS+=(--state-file "$STATE_FILE")
[[ "$ASK_REDUNDANCY" == true ]] && ARGS+=(-r)

"${PY[@]}" -m jev.cli "${ARGS[@]}" "$@"
