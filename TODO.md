# RockDove — Implementation Backlog

Contiene todos los cambios y features a implementar.

## Estado actual

| Componente | Estado |
|---|---|
| Server: peer registry + WS push | ✅ funcional |
| Server: metrics endpoint + recommender | ✅ funcional — colecta latencia y sube redundancia |
| Server: org/realm isolation (OIDC multi-realm) | ✅ funcional |
| Server: group scopes (admin configurable) | ✅ funcional |
| Server: invite tokens para agentes headless | ✅ funcional |
| Agent: RS encoder/decoder + UDP | ✅ funcional |
| Agent: heartbeat loop + auto re-registro | ✅ re-registra si TTL vence (server restart) |
| Headless agent Docker deploy | ✅ Dockerfile (uv) + docker-compose.headless.yml |
| Device tokens per-dispositivo | ✅ autogenerados, revocables, temporales o indefinidos |
| Agent: AppImage / distribución Electron | ✅ funcional (arreglado) |
| Agent: storage path XDG-compliant | ✅ `~/.local/share/rockdove` |
| Agent: JWT push desde UI después de login | ✅ funcional |
| Agent: token_store (JWT dinámico en runtime) | ✅ funcional |
| Admin panel (UI) | ✅ visibilidad de grupos + invites IoT |
| OIDC / SSO en Electron | ✅ loopback flow con browser externo |
| Peer invite tokens | ✅ funcional |
| Agent: `report_metrics()` | ✅ llamada post-transfer (loss_rate) y en background RTT probe |
| Agent: medición real de RTT/jitter/loss | ✅ `metrics/probe.py` — HTTP RTT a peers cada 60s |
| Persistencia en servidor | ✅ Redis — peers con TTL, métricas con LPUSH/LTRIM |
| Transfer history persistido | ✅ SQLite en agente (`storage/db.py`) + `GET /transfer/history` |
| Documentación de infraestructura de red | ✅ `docs/NETWORK_INFRA.md` — escenarios, matriz, recomendaciones |
| Feature flags | ❌ no existe |
| Dynamic FEC | ❌ estático por transferencia |
| NAT traversal / relay | ❌ no existe |

---

## Fixes aplicados en esta sesión

### ✅ AppImage: agente no arrancaba (`ModuleNotFoundError: No module named 'main'`)

- `src/main.py` tenía `\"\"\"` (backslashes literales antes de triple-quotes) → syntax error → PyInstaller marcaba `main` como `invalid module` y no lo bundleaba
- `src/__init__.py` convertía `src/` en un paquete Python, rompiendo la resolución de imports de PyInstaller con `pathex=["src"]`
- `run.py` manipulaba `sys.path` innecesariamente en modo frozen (PyInstaller ya provee `FrozenImporter` en `sys.meta_path`)

### ✅ AppImage: storage path read-only (`OSError: [Errno 30] Read-only file system: 'data'`)

- `STORAGE_PATH` defaulteaba a `"./data"` (path relativo al CWD del AppImage montado)
- Ahora resuelve a `$XDG_DATA_HOME/rockdove` o `~/.local/share/rockdove`

### ✅ OIDC: SSO abría Keycloak dentro de Electron en lugar del browser del sistema

- `startLogin()` usaba monkey-patching de `window.open` + `signinPopup()` — muy frágil
- Ahora usa `_manager._client.createSigninRequest()` para generar la URL con PKCE, la abre via `shell.openExternal()`, y el loopback flow (`/auth/callback` → `/auth/poll`) completa el intercambio

### ✅ UI: 307 redirects en cada request al agente

- `agentApi` usaba `/files` y `/transfer` sin trailing slash → FastAPI redirigía a `/files/` y `/transfer/` en cada call
- Arreglado en `api.ts`

### ✅ UI: React StrictMode en build de producción

- `StrictMode` en React 18 double-invoca effects en dev para detectar side effects → `useEffect` de `FileList` se ejecutaba 2 veces al montar, generando ráfagas de requests
- Sacado de `main.tsx` para el AppImage

---

## Fixes aplicados — sesión 2

### ✅ JWKS URL roto dentro de Docker

El servidor intentaba fetch a `localhost:8081` desde dentro del container para obtener las claves públicas de Keycloak. Ese hostname no existe dentro de la red Docker — el request fallaba silenciosamente y todos los JWTs eran rechazados.

Fix: `OIDC_KEYCLOAK_URL=http://keycloak:8080` en `docker-compose.yml` (hostname interno del servicio). `_jwks_url()` en `verifier.py` usa este hostname interno para el fetch de claves, pero valida el claim `iss` del JWT contra la URL pública (la que el usuario ve en el browser), evitando errores de validación de issuer.

### ✅ Agente no se registraba en modo OIDC

El agente arranca antes de que el usuario haga login. En el primer intento de registro no tenía JWT, la request fallaba con 401, y el agente nunca se recuperaba.

Fix: flujo JWT push desde la UI después del login OIDC. Cuando el usuario completa el login, la UI llama `POST /auth/token` con el access token. El agente lo almacena en `token_store` y lanza inmediatamente un nuevo intento de registro con el JWT en el header `Authorization: Bearer`.

### ✅ Service token `org_id` hardcodeado

`deps.py` ponía `org_id="dev"` para los service tokens aunque hubiera un `OIDC_ISSUER` configurado. Agentes desplegados con `AGENT_SERVICE_TOKEN` en realms distintos al de desarrollo quedaban en la org incorrecta.

Fix: cuando `OIDC_ISSUER` está disponible, se deriva el `org_id` a partir del realm del issuer en lugar de usar el literal `"dev"`.

### ✅ Invite `org_id` ignoraba el realm del caller

El endpoint de creación de invites siempre usaba `body.org_id` para el campo `org_id` del token generado, sin verificar a qué realm pertenecía el peer que hacía la llamada. Un peer autenticado en el realm A podía generar invites válidos para el realm B.

Fix: en modo OIDC, el endpoint ahora usa `caller.org_id` (extraído del JWT del caller) en lugar de `body.org_id`.

### ✅ Mapper de grupos no activo en Keycloak

El realm JSON (`rockdove-realm.json`) sólo se importa en el primer arranque de Keycloak. Las instancias existentes que ya tenían el realm importado sin el mapper de grupos no emitían el claim `groups` en el JWT.

Fix: el mapper se añade vía la API de administración de Keycloak en runtime (script de inicialización), independientemente del estado del realm existente.

### ✅ Panel admin no aparecía en la UI

La detección de admin dependía de que el claim `groups` estuviera presente en el JWT del usuario. Los tokens emitidos antes del fix anterior no incluían ese claim, por lo que ningún usuario era reconocido como admin.

Fix: detección server-side. La UI ahora sondea `GET /peers/scopes`: respuesta 200 significa que el peer tiene permisos de admin; respuesta 403 significa que no. Esto elimina la dependencia del claim `groups` en el cliente.

---

## ✅ P0.1 · Métricas reales — COMPLETADO

- `metrics/probe.py`: loop cada 60s, HTTP RTT (5 pings) a cada peer online, reporta a servidor
- `transfers/router.py`: al terminar cada send, reporta `loss_rate = recovered_blocks / total_blocks` y `elapsed_ms`
- `server_client.get_full_recommendation()`: fetch en paralelo para sender **y** target; usa `max` → si cualquier extremo tiene alta latencia, sube redundancia
- `TransferResult` ahora incluye `effective_redundancy`, `quality`, `profile_name` para que la UI los muestre

---

## ✅ P0.2 · Persistencia del servidor — COMPLETADO

- Peers en Redis hash `peer:{org_id}:{peer_id}` con TTL = `HEARTBEAT_TTL_S`
- Heartbeat = `EXPIRE` del key, el peer desaparece solo si deja de latir
- Métricas en Redis list `metrics:{peer_id}` con `LPUSH` + `LTRIM` (max 10 muestras)
- Redis en `docker-compose.yml` como servicio propio

---

## P1 — Diferenciadores académicos

### P1.1 · Dynamic Adaptive FEC

**Por qué:** esto es el salto de "TP con RS" a "adaptive FEC platform". Es el feature más innovador.

**Concepto:** en lugar de un `redundancy_level` fijo para toda la transferencia, ajustarlo por chunks basado en pérdida observada.

**Dónde:** `client/agent/src/rs/encoder.py`, `client/agent/src/transfers/router.py`

**Protocolo:**

1. Dividir el archivo en chunks de N bloques (configurable, default 200)
2. Enviar chunk 0 con redundancia inicial (la del slider)
3. El receiver reporta al sender: `{chunk_id, received, total}` vía el canal HTTP ya existente
4. El sender calcula `observed_loss = 1 - received/total` y ajusta redundancia para chunk 1
5. Repetir

```python
# transfers/router.py — nuevo campo en TransferResult
class ChunkResult(BaseModel):
    chunk_id: int
    received_blocks: int
    total_blocks: int
    redundancy_used: float

class TransferResult(BaseModel):
    # ... existing fields
    chunks: list[ChunkResult] = []
    redundancy_timeline: list[float] = []  # redundancy per chunk — gráfico en UI
```

**Complejidad:** L
**Dependencia:** P0.1 (necesita métricas para decidir)

---

### P1.2 · Network Profiles

**Por qué:** en lugar de que el usuario ajuste el slider sin contexto, el sistema sugiere un perfil y explica por qué.

**Dónde:** `server/src/metrics/recommender.py` + `client/agent/src/config.py`

**Implementación:**

- Agent declara un `network_hint` en register: `"lan" | "wifi" | "cellular" | "satellite" | "auto"`
- Con `"auto"`: server infiere desde las métricas recibidas
- Server retorna `quality`, `recommended_level`, y `profile_name` en la recomendación

```python
PROFILES = {
    "lan":       {"redundancy": 0.05, "block_size": 64, "pacing_ms": 0},
    "wifi":      {"redundancy": 0.10, "block_size": 32, "pacing_ms": 2},
    "cellular":  {"redundancy": 0.30, "block_size": 32, "pacing_ms": 10},
    "satellite": {"redundancy": 0.50, "block_size": 16, "pacing_ms": 50},
}
```

**Complejidad:** S

---

### ✅ P1.3 · OIDC real con Keycloak — completado (client + server)

El flujo SSO está operativo end-to-end:

**Client side:**

- `startLogin()` genera la URL de autorización con PKCE y la abre en el browser del sistema
- Keycloak redirige a `http://127.0.0.1:8000/auth/callback` (agente local)
- El agente almacena el code; la UI hace polling y completa el token exchange con `signinCallback()`
- La UI empuja el JWT al agente vía `POST /auth/token`; el agente re-registra con el servidor

**Server side:**

- `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_ENABLED=true` configurados en el servidor
- JWT verification con JWKS fetch desde el hostname interno de Keycloak
- `peer_id` asignado como `JWT sub` en modo OIDC
- `org_id` derivado del realm del issuer para service tokens
- Invite `org_id` usa el realm del caller en modo OIDC

---

## P2 — Distribución enterprise y conectividad

### P2.1 · Peer Capability System

**Por qué:** prerequisito para el relay. El servidor necesita saber qué peers pueden actuar como
relay antes de poder sugerirlos como intermediarios.

**Dónde:** `server/src/peers/router.py` + `client/agent/src/server_client.py`

**Implementación:** el agente anuncia capacidades en el heartbeat:

```python
class HeartbeatPayload(BaseModel):
    relay_capable: bool = False      # puede actuar como relay
    store_and_forward: bool = False  # puede encolar transferencias para peers offline
    network_hint: str = "auto"       # lan / wifi / cellular / satellite
    bandwidth_class: str = "unknown" # low / medium / high
```

El servidor expone estas capacidades en `GET /peers` para que los emisores puedan elegir
rutas inteligentemente.

**Complejidad:** S

---

### P2.2 · Relay Fallback (peer-to-peer via relay nativo)

**Por qué:** desbloquea casos donde el UDP directo no funciona — NAT sin forwarding, redes
segmentadas, peers móviles sin VPN. Elimina la dependencia de infraestructura externa para la
conectividad básica.

**Escenario:**

```
Peer A (NAT) ──► Relay C (IP pública) ──► Peer B (NAT)
```

**Protocolo:**

1. El sender intenta `POST /transfer/receive` directo a B — si falla (timeout / error), pasa al paso 2.
2. El sender consulta al servidor: `GET /peers/relay?target={peer_b_id}` — el servidor retorna
   el relay con mejor conectividad con B, priorizando peers con `relay_capable=true`.
3. El sender envía bloques UDP al relay. El relay re-encapsula y reenvía a B.
4. El relay puede **re-calcular redundancia** para el segundo hop si ese link tiene peor calidad.

**Dónde:**

- `server/src/peers/router.py` — nuevo endpoint `GET /peers/relay`
- `client/agent/src/rs/transport.py` — modo relay en el sender
- `client/agent/src/transfers/router.py` — lógica de relay receiver

**Complejidad:** L
**Dependencia:** P2.1 (necesita capabilities en heartbeat)

---

### P2.3 · Store-and-Forward para peers offline

**Por qué:** en topologías con conectividad intermitente (satélite, industrial, campo), el receptor
puede no estar online cuando el emisor envía. El relay almacena y entrega cuando el peer vuelve.

**Escenario:**

```
HQ envía → Relay concentrador → [Sensor offline]
                               ↓ vuelve online
                               ← relay entrega los bloques almacenados
```

**Implementación:**

- El relay con `store_and_forward=true` acepta transferencias para peers offline.
- Almacena los bloques RS en disco temporalmente (TTL configurable).
- Cuando el peer target se registra o hace heartbeat, el relay inicia la entrega.
- El peer emisor recibe confirmación del relay (no del destinatario final) — el estado de la
  transferencia pasa a `relayed` hasta que el destinatario confirme recepción.

**Nuevo estado de transferencia:**

| Estado | Significado |
|---|---|
| `ok` | Recibido y verificado por el destinatario final |
| `degraded` | RS recovery en tránsito, recibido íntegro |
| `relayed` | En cola en el relay, pendiente de entrega al destinatario |
| `failed` | No recuperable o expiró en el relay |

**Complejidad:** L
**Dependencia:** P2.2 (relay básico primero)

---

### P2.4 · Feature Flags en servidor

**Por qué:** permite activar relay, store-and-forward y dynamic FEC por ambiente sin redeploy.
Crítico para gradual rollout de los features de P2.

**Dónde:** nuevo `server/src/features/router.py`

```python
FEATURES = {
    "dynamic_fec":        os.getenv("FF_DYNAMIC_FEC", "false") == "true",
    "relay_fallback":     os.getenv("FF_RELAY_FALLBACK", "false") == "true",
    "store_and_forward":  os.getenv("FF_STORE_AND_FORWARD", "false") == "true",
    "quic_transport":     os.getenv("FF_QUIC_TRANSPORT", "false") == "true",
}

@router.get("/")
async def get_features() -> dict:
    return FEATURES
```

Agent lo lee al arrancar y guarda en un singleton `features`. Cada codepath nuevo hace
`if features.relay_fallback:`.

**Complejidad:** S

---

### ✅ P2.5 · Historial de transferencias SQLite — COMPLETADO

- `storage/db.py` — init, insert, list con `aiosqlite`
- Persiste sent (con `peer_id`, `filename`, `redundancy`, `quality`) y received (con `file_size`, `recovered_blocks`)
- `GET /transfer/history?limit=50` — `HistoryEntry` model
- Inicializado en el lifespan de `main.py`; se cierra ordenadamente al apagar el agente

---

### P2.6 · PostgreSQL + historial de métricas en servidor

**Por qué:** con Redis se pierde el historial al reiniciar (aunque el TTL es alto). Con Postgres
se puede analizar tendencias históricas, mejorar el recommender con datos reales acumulados, y
tener auditoría de transferencias para el relay.

**Dónde:** `server/src/db/` con SQLAlchemy async

Tablas mínimas:

- `peer_metrics(peer_id, ts, rtt_ms, jitter_ms, loss_rate)`
- `transfers_audit(transfer_id, sender, receiver, relay, bytes, status, ts)`

**Complejidad:** L
**Dependencia:** P0.2 (Redis primero, Postgres como upgrade)

---

## ✅ P2.x · Headless Agent Deployment — COMPLETADO

### Qué hay

**`client/agent/Dockerfile`** — imagen funcional construida con `uv export` desde el lockfile para deps reproducibles.

**`client/agent/docker-compose.headless.yml`** — compose listo para copiar al dispositivo. Lee variables desde `.env`.

**Heartbeat auto-recovery** — si el peer TTL vence en Redis (server se reinicia), el siguiente heartbeat devuelve 404 y el agente se vuelve a registrar automáticamente sin intervención humana.

### Device tokens — sistema de autenticación por dispositivo ✅

Módulo `server/src/device_tokens/`. Reemplaza el token compartido por tokens únicos, autogenerados y revocables.

**Formato:** `rd_<43-char base64url>` — 256 bits de entropía, imposible de adivinar.

**API (admin only):**

| Endpoint | Acción |
|---|---|
| `POST /device-tokens/` | Crea token. Retorna el valor completo **solo en esta respuesta** |
| `GET /device-tokens/` | Lista tokens del org con `token_preview` (primeros 12 chars + `...`) |
| `DELETE /device-tokens/{id}` | Revoca inmediatamente — el token falla en el próximo request |

**Creación — campos:**

```json
{
  "label": "Sensor Planta A",
  "peer_id": "sensor-a1",
  "ttl_seconds": 2592000
}
```

`ttl_seconds: null` → indefinido. El token se borra de Redis al vencer (sin cron).

**Storage Redis:**

- `device_token:{value}` → hash con metadata (lookup de auth)
- `device_token_rev:{org}:{id}` → value (para revocar por ID)
- `device_tokens_idx:{org}` → set de IDs (para listar)

**Auth flow en `deps.py`:**

1. `AGENT_SERVICE_TOKEN` estático (legado, solo si está configurado)
2. Redis lookup `device_token:{bearer}` → `CallerInfo(is_service=True, peer_id=<peer_id del token>)`
3. OIDC JWT (usuarios humanos)

### Flujo completo para un dispositivo headless

**Paso 1 — Admin genera un device token**

```http
POST /device-tokens/
Authorization: Bearer <admin-jwt>

{ "label": "Sensor Planta A", "peer_id": "sensor-a1", "ttl_seconds": null }
```

Respuesta (el campo `token` solo aparece aquí):

```json
{
  "id": "550e8400-...",
  "label": "Sensor Planta A",
  "token": "rd_dW6awd00XpaS1PqJzK8mBnLcVt9...",
  "token_preview": "rd_dW6awd00Xp...",
  "expires_at": null
}
```

**Paso 2 — Operador configura el dispositivo**

`.env` en el dispositivo:

```
PEER_ID=sensor-a1
SERVER_URL=http://my-server:8080
AGENT_API_URL=http://<device-ip>:8000
AGENT_SERVICE_TOKEN=rd_dW6awd00XpaS1PqJzK8mBnLcVt9...
```

```bash
docker compose -f docker-compose.headless.yml up -d
```

**Paso 3 — El agente se auto-mantiene**

- Se registra en el server al arrancar usando el device token como Bearer
- Heartbeat cada 15s renueva el TTL Redis del peer
- Si el server se reinicia → siguiente heartbeat (404) dispara re-registro automático
- Si el token vence → heartbeat empieza a fallar 401 → admin genera uno nuevo

### Binario alternativo (sin Docker)

```bash
chmod +x rockdove-agent.AppImage
PEER_ID=sensor-a1 SERVER_URL=http://server:8080 \
AGENT_API_URL=http://$(hostname -I | awk '{print $1}'):8000 \
AGENT_SERVICE_TOKEN=rd_dW6awd00XpaS1... \
./rockdove-agent.AppImage
```

---

## P3 — Roadmap ambicioso

| Feature | Descripción | Complejidad |
|---|---|---|
| **NAT hole punching activo** | Servidor como signaling relay: coordina intercambio de IPs + STUN para que ambos peers establezcan UDP directo detrás de NAT | L |
| **Smart routing multi-hop** | Server sugiere `A → relay_C → relay_D → B` basado en graph de conectividad entre peers. Optimización de ruta por latencia + costo | XL |
| **ML redundancy** | Reemplazar tabla de umbrales hardcodeada por modelo simple (regresión logística) entrenado sobre historial de transferencias. Input: RTT, jitter, loss histórico, network_hint | L |
| **Peer-to-peer invite flow** | A genera un JWT de invitación fuera de banda (QR, email). B lo usa para registrarse en la org de A sin intervención del admin | S |

---

## Secuencia de sprints sugerida

```
Sprint 1 (P0):   ✅ Redis en server · métricas desde transfers
Sprint 2 (P1a):  dynamic FEC · network profiles
Sprint 3 (P1b):  feature flags · peer capability system
Sprint 4 (P2a):  relay fallback básico (UDP direct → relay fallback)
Sprint 5 (P2b):  store-and-forward · historial relay en SQLite
Sprint 6 (P3):   NAT hole punching activo · QUIC transport
```

**El feature con mayor impacto académico es dynamic FEC (P1.1):** transforma el sistema de
"archivo con RS estático" a "plataforma con FEC adaptativo en tiempo real".

**El feature con mayor impacto de producto es el relay (P2.2):** desbloquea todos los escenarios
donde el UDP directo no funciona — que es la mayoría de los entornos de internet pública.

---

## Sprint actual — Transport Toggle + Relay con tag efímero

### Resumen

Dos features en paralelo que se complementan:

1. **Toggle UDP ↔ QUIC** — abstracción de capa de transporte. UDP = raw socket sin TLS (comportamiento actual). QUIC = `aioquic` sobre el mismo puerto UDP, con TLS 1.3 nativo, QUIC DATAGRAM extension (RFC 9221) para mantener la semántica unreliable que el RS FEC necesita.
2. **Relay con tag efímero** — peers que el admin o el creador del peer puede flagear como `relay_capable`. Reciben bloques RS, los reenvían al destino real, y destruyen el buffer (nunca escriben a STORAGE_PATH). Tag efímero por sesión de relay.

---

### Feature A · Transport Toggle (UDP ↔ QUIC)

#### Diseño del transporte

```
TRANSPORT_MODE=udp  (default)
  └─► UDPTransport — raw asyncio.DatagramProtocol, sin TLS, puerto UDP_PORT

TRANSPORT_MODE=quic
  └─► QUICTransport — aioquic sobre el mismo UDP_PORT
        · TLS 1.3, cert autogenerado en STORAGE_PATH al primer arranque
        · QUIC DATAGRAM extension: bloques RS como datagrams (unreliable+encrypted)
        · verify_peer=False en dev (sin distribución de CA)
        · RS FEC sigue demostrando recuperación de pérdida sobre QUIC datagrams
```

Los dos transportes son **mutuamente exclusivos** en el mismo puerto. El toggle se hace via `TRANSPORT_MODE` en el `.env` (cambio requiere restart del agente, igual que UDP_PORT).

El peer anuncia su `transport` en el registro al servidor. Cuando peer A envía a B, lee el `transport` de B en su `PeerInfo` y usa el cliente correspondiente. Si los modos no coinciden, la transferencia falla con error descriptivo.

#### Arquitectura interna del agente

`rs/transport.py` pasa de un archivo con una clase concreta a un módulo con:

- `BaseTransport` (ABC): interfaz `start / send / collect / stop`
- `UDPTransport`: implementación actual sin cambios de lógica, hereda de `BaseTransport`
- `QUICTransport`: nueva implementación con `aioquic`
- `get_transport() → BaseTransport`: singleton lazy
- `set_transport(t: BaseTransport)`: llamado en `main.py` lifespan según `TRANSPORT_MODE`

`transfers/router.py` reemplaza `from rs.transport import udp` por `from rs.transport import get_transport` y llama `get_transport().send(...)` / `get_transport().collect(...)`.

#### Cert generation (QUIC)

Al arrancar con `TRANSPORT_MODE=quic`, `QUICTransport.start()` llama a `_ensure_tls_certs(cert_path, key_path)`. Si los archivos ya existen, los reutiliza. Si no, los genera con `cryptography` (RSA 2048, auto-firmado, CN=rockdove-peer, validez 10 años). Los paths viven en `STORAGE_PATH/quic_cert.pem` y `STORAGE_PATH/quic_key.pem`.

#### Archivos a modificar

| Archivo | Cambio |
|---|---|
| `client/agent/pyproject.toml` | Agrega `aioquic>=1.0.0`, `cryptography>=42.0.0` |
| `client/agent/src/config.py` | `TRANSPORT_MODE: Literal["udp","quic"] = "udp"` |
| `client/agent/src/rs/transport.py` | Refactor completo: `BaseTransport` + `UDPTransport` + `QUICTransport` + `get/set_transport` |
| `client/agent/src/main.py` | Selección de transporte en lifespan según `TRANSPORT_MODE` |
| `client/agent/src/transfers/router.py` | `get_transport()` en lugar de `udp` singleton |
| `client/agent/src/server_client.py` | Incluye `transport` en `register()` body |
| `server/src/peers/router.py` | `PeerRegistration` + `PeerInfo` + Redis hash incluyen campo `transport` |
| `client/ui/src/types.ts` | `PeerInfo.transport?: "udp" \| "quic"` |
| `client/ui/src/components/PeerList.tsx` | Badge UDP/QUIC en cada peer |

---

### Feature B · Relay con tag efímero

#### Flujo directo (sin relay)

```
A → POST {B.api_url}/transfer/receive
A → UDP/QUIC packets → B
A → poll B/status → ok | degraded | failed
```

#### Flujo relay (B inalcanzable)

```
1. A intenta POST {B.api_url}/transfer/receive → httpx.RequestError (timeout / conn refused)
2. A → GET {server}/peers/relay?target=B → server devuelve Relay C (relay_capable=true)
3. A → POST {C.api_url}/transfer/receive  body: { ..., relay_to: "B", relay_tag: "rly-a3f2" }
4. A → UDP/QUIC packets → C  (mismos bloques RS que habría enviado a B)
5. C colecta los bloques (collect en buffer efímero)
6. C → POST {B.api_url}/transfer/receive  (request estándar a B)
7. C → reenvía los mismos paquetes → B
8. C polls B hasta que B devuelve status final
9. C → _transfers[tid] = { status: "relayed", relay_tag: "rly-a3f2", relay_target: "B", final_status: <el de B> }
10. C NO escribe a STORAGE_PATH — buffer destruido después del reenvío
11. A polls C → recibe { status: "relayed", relay_tag: "rly-a3f2" }
```

#### Tag efímero

El relay genera `relay_tag = f"rly-{secrets.token_hex(4)}"` al aceptar la request de relay (ej: `"rly-a3f2b1c0"`). Este tag:

- Es único por sesión de relay
- Viaja en `TransferResult` al sender
- Aparece en la UI del sender como indicador de que la entrega fue vía relay
- No se persiste en SQLite (`insert_transfer` no se llama en modo relay — es efímero)

#### Capability system

El admin (o el agente mismo via config) puede declarar `relay_capable=true`. Dos vías:

**Vía env var (self-declared):** el agente lee `RELAY_CAPABLE=true` del `.env` y lo anuncia en el body de `POST /peers/register`.

**Vía admin API (server-side override):** `POST /peers/{peer_id}/capabilities` (admin-only). Actualiza el `relay_capable` en el Redis hash del peer. Persiste hasta que el peer se re-registra (el re-register también envía su propio `relay_capable` desde config).

El campo `relay_capable` se almacena en el Redis hash como string `"true"/"false"` (igual que `udp_port`).

#### Nuevo endpoint en el server: GET /peers/relay

```python
GET /peers/relay?target={peer_id}
→ PeerInfo del mejor relay disponible (relay_capable=true, misma org, distinto al target y al caller)
→ 404 si no hay ninguno disponible
```

Selección de relay: por ahora devuelve el primero con `relay_capable=true` (FIFO). En el futuro: priorizar por métricas de latencia al target.

#### Archivos a modificar

| Archivo | Cambio |
|---|---|
| `client/agent/src/config.py` | `RELAY_CAPABLE: bool = False` |
| `client/agent/src/rs/models.py` | Agrega `relayed = "relayed"` a `TransferStatus` |
| `client/agent/src/transfers/models.py` | `ReceiveRequest.relay_to`, `ReceiveRequest.relay_tag`; `TransferResult.relay_tag`, `TransferResult.relay_target` |
| `client/agent/src/transfers/router.py` | Relay fallback en `send_file()`; nueva función `_process_relay(req)`; `receive_transfer()` rutea según `relay_to` |
| `client/agent/src/server_client.py` | `relay_capable` en `register()`; nuevo método `get_relay_for_peer(target_id)` |
| `server/src/peers/router.py` | `relay_capable` en `PeerRegistration`, `PeerInfo`, Redis; endpoint `GET /peers/relay`; endpoint `POST /peers/{id}/capabilities` |
| `client/ui/src/types.ts` | `PeerInfo.relay_capable?: boolean` |
| `client/ui/src/api.ts` | `serverApi.getRelayPeer(targetId)`, `serverApi.updateCapabilities(peerId, relay_capable)` |
| `client/ui/src/components/PeerList.tsx` | Badge relay en peers con `relay_capable=true` |
| `client/ui/src/components/AdminPanel.tsx` | Tab "Relays": lista peers online, toggle `relay_capable` por peer |

---

### Estado de implementación

| Sub-feature | Estado |
|---|---|
| `BaseTransport` + refactor `UDPTransport` | ✅ `rs/transport.py` |
| `QUICTransport` con aioquic + cert gen | ✅ `rs/transport.py` |
| Toggle `TRANSPORT_MODE` en config + lifespan | ✅ `config.py` + `main.py` |
| `transport` en registro de peer (server + agent) | ✅ `server_client.py` + `peers/router.py` |
| Badge UDP/QUIC en UI | ✅ `PeerList.tsx` |
| CERT_HELLO protocol (98-byte datagram con peer_id + fingerprint) | ✅ `rs/transport.py` |
| Approval gate en receiver (`wait_for_approval`) | ✅ `transfers/router.py` |
| Endpoints `/transfer/incoming`, `/accept`, `/reject` | ✅ `transfers/router.py` |
| `IncomingConnectionsBanner` — UI accept/reject con cert info | ✅ `ui/src/components/` |
| Test suite QUIC coverage (73 tests passing) | ✅ `tests/test_transport.py` |
| `RELAY_CAPABLE` en config + registro | ❌ pendiente |
| `relay_capable` en server (Redis + endpoints) | ❌ pendiente |
| `GET /peers/relay` en server | ❌ pendiente |
| `POST /peers/{id}/capabilities` en server | ❌ pendiente |
| Relay fallback en `send_file()` | ❌ pendiente |
| `_process_relay()` con tag efímero | ❌ pendiente |
| Badge relay + tab Relays en UI | ❌ pendiente |
