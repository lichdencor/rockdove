# Jev — Decisiones de Redundancia y Relay con TypeSafe System One

RockDove usa **Jev** (primer modelo *System One* de TypeSafe AI) como capa de
decisión sobre la telemetría de red que reportan los pares. En lugar de
generar texto, Jev recibe un `state` (contexto) + preguntas *tipadas* y
devuelve una decisión calibrada por pregunta en una sola pasada en paralelo:
`Choice`, `Noul` (sí/no) o `Score`.

Este documento explica **qué** decide Jev, **cómo** está cableado en el
servidor y **cómo** probarlo con datos mockeados entre dos hosts.

## Qué decide Jev

Dado un enlace `source → target` con sus métricas promedio (RTT, jitter,
pérdida, perfil de red), una **única llamada** a Jev responde tres preguntas
en paralelo:

| Pregunta | Tipo | Respuesta |
|---|---|---|
| `redundancy_band` | `Score` | Grado de redundancia Reed-Solomon (gradiente r en `[0.05, 0.50]`) |
| `should_relay` | `Noul` | Si conviene **saltar por un relay** en vez de ir directo |
| `relay_target` | `Choice` | Cuál relay usar (`direct` = sin relay) |

### ¿Una llamada Jev para todo o una por métrica?

**Una sola llamada con múltiples preguntas sobre el mismo `state`.** Es el
patrón que recomienda TypeSafe:

- Jev evalúa todas las preguntas **en paralelo** sobre la misma `state`; la Nª
  pregunta extra cuesta solo tokens de entrada, **no latencia**.
- Las tres preguntas son *juicios independientes* sobre la misma telemetría,
  así que pertenecen al mismo request. Hacer una llamada por métrica
  multiplicaría los round-trips sin ganar nada.
- El código combina las respuestas: si la confianza de la redundancia baja,
  se cae a la tabla determinista; el relay se decide con su propia señal Noul +
  Choice.

## Arquitectura (server)

```
POST /metrics/report (agentes) ──► Redis (ventana deslizante 10 muestras/peer)
                                        │
GET /jev/transit/{source}/{target}?relay=relay-core
        │  lee métricas promedio de ambos hosts + registros de peer
        ▼
  jev/decider.decide_transit()
        │  construye state + 3 preguntas tipadas
        ▼
  jev/client.decide()  ──►  POST https://openrouter.ai/api/alpha/decisions
        │                      model: typesafe/jev-1.13
        ▼
  parse + confidence gate (JEV_CONFIDENCE_THRESHOLD)
        │
        ├─ confianza alta ──► usa la respuesta de Jev
        └─ confianza baja / Jev off / error ──► metrics.recommender (tabla)
```

### Módulos nuevos (`server/src/jev/`)

| Archivo | Responsabilidad |
|---|---|
| `client.py` | Cliente async (httpx) del endpoint Decisions de OpenRouter |
| `decider.py` | Construye `state`+preguntas, llama Jev, interpreta respuestas y aplica el fallback determinista |
| `router.py` | Endpoints HTTP `/jev/*` |
| `mock.py` | Seed de telemetría mockeada entre dos hosts + relays |

## Configuración (env)

| Variable | Default | Notas |
|---|---|---|
| `JEV_ENABLED` | `false` | `false` ⇒ siempre tabla determinista (Jev off) |
| `OPENROUTER_API_KEY` | `` | Key de OpenRouter (server-side, nunca en browser) |
| `JEV_MODEL` | `typesafe/jev-1.13` | Id del modelo TypeSafe en OpenRouter |
| `JEV_BASE_URL` | `https://openrouter.ai/api/alpha/decisions` | Endpoint Decisions API |
| `JEV_TIMEOUT_S` | `10.0` | Timeout HTTP de la llamada |
| `JEV_CONFIDENCE_THRESHOLD` | `0.85` | Umbral para actuar con la respuesta de Jev |

> La API key debe ir en `.env` del servidor (que `docker-compose.yml` ya carga
> vía `env_file: ../.env`). Nunca la incluyas en el frontend.

> El endpoint `type=/jev/../alpha/decisions` responde `200` con `answers`; el
> nombre en la respuesta incluye un sufijo por snapshot (ej.
> `typesafe/jev-1.13-20260917`): es esperado.

## Credenciales

1. Creá una key en <https://openrouter.ai/settings/keys>.
2. Pegala en `.env`:
   ```dotenv
   OPENROUTER_API_KEY=sk-or-v1-...
   JEV_ENABLED=true
   ```

## Probar con datos mockeados entre dos hosts

El seed crea dos pares (hosts) + un relay candidato e inyecta `MetricReport`s
en Redis, de modo que el pipeline completo funcione sin agentes reales.

```bash
cd server
uv sync
uv run uvicorn main:app --reload --app-dir src
```

```bash
# escenarios disponibles: satellite | lan | wifi
curl -X POST http://localhost:8080/jev/mock/seed/satellite?relay=relay-core

# luego, decisión Jev para ese enlace:
curl "http://localhost:8080/jev/transit/edge-hq/edge-remote?relay=relay-core"

# métricas/axios del estado de Jev:
curl http://localhost:8080/jev/status
```

Respuesta del transit (ejemplo, degradation satellite):

```json
{
  "redundancy_level": 0.5,
  "quality": "critical",
  "profile_name": "Satellite",
  "should_relay": true,
  "relay_peer_id": "relay-core",
  "source": "edge-hq",
  "target": "edge-remote",
  "evidence": { ... },
  "source_name": "jev",
  "confidence": 0.92
}
```

### Palanca de preview

`GET /jev/transit/...?preview=true` fuerza la llamada a Jev aunque
`JEV_ENABLED=false` (útil en desarrollo para ver el comportamiento Jev sin
activarlo todavía). Si no hay key configurada, degrada a la tabla determinista.

## Diseño de decisiones: descomposición y umbrales

- **Descomponé** cada conclusión en preguntas independientes (Noul/Choice/Score)
  y **combiná en código**, en vez de una pregunta monstruo. Acá: redundancia,
  relay-sí-no y relay-cuál son tres condiciones separadas.
- **Confidence-gated**: Jev actúa solo por encima de `JEV_CONFIDENCE_THRESHOLD`;
  por debajo, cae a las reglas deterministas existentes (`metrics.recommender`).
  La feature es **aditiva**: nunca degrada el comportamiento actual si Jev está
  apagado o falla (network/auth/timeout ⇒ `source_name: "deterministic"`).
- Elegir el umbral según el costo del error, no por redondeo: en un link
  satelital vale más aceptar más redundancia y fallar menos.

## Costo y latencia

Jev se cobra por tokens de entrada (salida gratis). Un request con 3 preguntas
sobre la telemetría de 2 hosts es del orden de **centésimas de dólar** y
responde en ~70–500 ms. Para una discusión económica del modelo ver
`docs/arquitectura_src.md` y la página del modelo en OpenRouter.