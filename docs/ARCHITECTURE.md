# Architecture — RockDove

## Overview

RockDove es una plataforma de transferencia de archivos peer-to-peer con corrección de errores Reed-Solomon (FEC) sobre UDP. El emisor codifica el archivo con redundancia matemática antes de enviarlo; el receptor reconstruye el original aunque se pierdan paquetes, sin retransmisión. La redundancia se ajusta automáticamente en función de métricas de red recolectadas en tiempo real por un servidor central.

El sistema separa coordinación de transferencia en dos planos independientes. El **plano de control** (servidor, una instancia en cloud) gestiona identidad de peers, métricas de red y rutas de relay. El **plano de datos** (agente, uno por máquina) ejecuta el motor RS, el socket UDP/QUIC y el almacenamiento local. Los archivos nunca pasan por el servidor; la transferencia es siempre directa, máquina a máquina.

---

## C4 Level 1 — Contexto del sistema

El sistema interactúa con tres tipos de actores externos: el **usuario desktop** que envía y recibe archivos desde la interfaz Electron; el **administrador de organización** que gestiona peers, scopes y políticas de acceso; y el **dispositivo edge/IoT** que opera headless autenticado con device token. El sistema se integra opcionalmente con **Keycloak** como proveedor de identidad OIDC externo para multi-tenancy.

![Contexto del sistema](informes/img/architecture.png)

---

## C4 Level 2 — Contenedores

| Contenedor | Tecnología | Puerto | Responsabilidad |
|---|---|---|---|
| Servidor de Coordinación | Python / FastAPI | 8080 TCP | Registro de peers, métricas, relay lookup, control de acceso |
| Neo4j | Base de datos de grafos | 7687 TCP | Grafo de peers con aristas `CONNECTS_TO` ponderadas por RTT/jitter/loss |
| Redis | Store en memoria | 6379 TCP | Buffer de métricas (últimas 10/peer), device tokens, org scopes, TTL de heartbeat |
| Keycloak | OIDC provider | 8081 TCP | Identidad, realms, grupos (opcional) |
| Agente Local | Python / FastAPI | 8000 TCP + 9001 UDP | Motor RS, capa de transporte, relay, almacenamiento, daemon |
| SQLite | Base de datos embebida | — | Historial local de transferencias |
| Shell Electron | Electron | — | Lanza el agente Python, carga la SPA, expone base URL via contextBridge |
| Interfaz Web | React + Vite + Tailwind | — | SPA: dashboard, diálogo de transferencia, panel admin, health charts |

**Flujos de comunicación:**

- Interfaz Web → Agente Local: HTTP `127.0.0.1:8000` (consultas de estado, inicio de transferencia)
- Interfaz Web ↔ Servidor: WebSocket `/peers/watch` (push de lista de peers en tiempo real)
- Agente Local → Servidor: HTTPS (registro, heartbeat, peer lookup, reporte de métricas, relay config)
- Agente Local ↔ Agente Remoto: UDP/QUIC directo puerto 9001 (bloques Reed-Solomon; los archivos nunca pasan por el servidor)
- Servidor → Neo4j: lectura/escritura de nodos `:Peer` y aristas `CONNECTS_TO`
- Servidor → Redis: lectura/escritura de métricas, tokens y estado de presencia
- Servidor → Keycloak: validación JWT via JWKS (opcional)

---

## C4 Level 3 — Componentes

### Servidor de Coordinación

| Componente | Responsabilidad |
|---|---|
| Peers Router | `POST /peers/register`, `POST /peers/{id}/heartbeat`, `GET /peers`, `GET /peers/{id}`, `GET /peers/relay`, `POST /peers/{id}/relay-config`, `POST /peers/{id}/incoming-policy`, WebSocket `/peers/watch` |
| Metrics Router | `POST /metrics/report`, `GET /metrics/recommendation/{id}`, `GET /metrics/history/{id}`, `GET /metrics/network-graph` |
| Device Tokens Router | Creación, listado y revocación de tokens `rd_*` por dispositivo |
| Invites Router | Tokens de invitación de un solo uso para incorporación de nuevos peers |
| Auth Middleware | Validación de JWT via JWKS de Keycloak; extracción de `org_id` (del realm) y `groups` |
| Neo4j Store | Persistencia del grafo de peers; consulta de rutas de relay por peso de arista |
| Redis Store | Buffer de métricas por peer (list, últimas 10); device tokens (hash + TTL); org scopes (JSON) |
| Redundancy Recommender | Promedia métricas del buffer, clasifica calidad de red, devuelve nivel de redundancia sugerido |

### Agente Local

| Componente | Responsabilidad |
|---|---|
| RS Encoder | Calcula SHA-256 del archivo, segmenta en bloques de k bytes, aplica RS sobre GF(2^8) para producir n bytes por bloque, construye datagramas con header de 30 bytes |
| RS Decoder | Colecta bloques recibidos, identifica posiciones de erasure, reconstruye algebraicamente, verifica SHA-256, produce estado `ok`/`degraded`/`failed`/`relayed` |
| Transport Layer | Interfaz `BaseTransport` con `UDPTransport` (asyncio DatagramProtocol raw) y `QUICTransport` (aioquic, TLS 1.3, DATAGRAM frames RFC 9221, CERT_HELLO identity frame, flujo de aprobación de conexiones entrantes); conmutable en runtime |
| Relay Engine | Colecta bloques en RAM (nunca en disco), resuelve destino via rutas estáticas o lookup al servidor, notifica al peer destino, reenvía bloques; tags: ephemeral, restricted, gateway |
| Server Client | Toda la comunicación HTTP con el servidor: registro, heartbeat, peer lookup, reporte de métricas, fetch de recomendación, relay config |
| Transfer Router | Endpoints `/transfer/*`: inicio de envío, recepción, historial, incoming connections |
| Files Router | Endpoints `/files/*`: listado, upload, download desde almacenamiento local |
| Metrics Probe | Loop en background (cada 60 s): mide RTT/jitter hacia peers online, reporta al servidor |
| Local Storage | Almacena archivos en `STORAGE_PATH` con índice SHA-256 |
| Transfer History | Persiste cada transferencia en SQLite: `transfer_id`, `direction`, `peer_id`, `filename`, `bytes`, `status`, `redundancy`, `recovered_blocks`, `total_blocks`, `quality`, `profile_name` |
| Auth Handler | OIDC+PKCE para humanos, validación de device tokens (`rd_*`), invite tokens de un solo uso; política de entrada configurable por `INCOMING_POLICY` env |
| Daemon Manager | `rs-agent daemon install/start/stop/status/uninstall`; systemd user unit (Linux), LaunchAgent plist (macOS), schtasks ONLOGON (Windows) |

---

## C4 Level 4 — Código

### Codificación Reed-Solomon

El proceso comienza al recibir el archivo completo en memoria. Se calcula el resumen criptográfico SHA-256 del contenido original para verificación posterior. El archivo se divide en segmentos de `k` bytes; el último se rellena con ceros si es necesario, y el tamaño original se incluye en el encabezado para que el receptor pueda eliminar el relleno. Para cada segmento se aplica aritmética sobre el cuerpo de Galois GF(2^8) y se generan `n−k` bytes adicionales de paridad. Estos símbolos tienen la propiedad de que cualquier subconjunto de `k` símbolos del total de `n` permite reconstruir el segmento original sin pérdida. Cada bloque codificado se empaqueta con un encabezado binario de 30 bytes que incluye `transfer_id`, `block_index`, `total_blocks`, parámetros `n`/`k`, flags y tamaño del archivo original.

### Decodificación Reed-Solomon

El receptor colecta bloques indexados a medida que llegan. Al conocer exactamente qué índices faltan (modelo de erasure), el decodificador usa álgebra de campos finitos para reconstruir los bloques ausentes a partir de los recibidos. Una vez reconstruidos todos los segmentos, se concatenan, se elimina el relleno y se verifica el SHA-256 contra el valor enviado por el emisor. El resultado es `ok` (sin pérdidas), `degraded` (pérdidas recuperadas por RS), `failed` (pérdidas superan capacidad RS o checksum incorrecto), o `relayed` (recibido vía un peer intermedio).

### Capa de transporte

Ambas implementaciones de transporte comparten la misma interfaz abstracta con cuatro operaciones: iniciar escucha, enviar bloque, colectar bloque recibido, y detener. En modo UDP, cada bloque RS se envía como un datagrama independiente sobre un socket asíncrono sin estado de sesión. En modo QUIC, se establece una sesión cifrada con TLS 1.3; los bloques RS se transmiten como frames DATAGRAM sin retransmisión (RFC 9221), preservando la semántica de pérdida necesaria para el modelo de erasure. Antes de enviar los bloques RS, el emisor envía un frame especial CERT_HELLO con su identidad criptográfica; el receptor registra la conexión como pendiente y espera aprobación del operador (auto-aprobación a los 30 s si no hay interacción). El transporte activo es seleccionable en runtime sin reiniciar el agente.

### Sistema de relay

Cuando el path directo falla, el agente emisor busca un peer con `relay_capable=true` a través del servidor o rutas estáticas configuradas. El relay colecta los bloques RS en memoria RAM exclusivamente (nunca escribe a disco), resuelve la dirección del peer destino, notifica al destino de la transferencia entrante y reenvía los bloques. La transferencia aparece como `relayed` en el historial de ambos extremos.

### Redundancia adaptativa

El agente ejecuta un loop de medición en background que calcula RTT y jitter hacia peers activos y los reporta al servidor. Al iniciar una transferencia, el servidor consulta las últimas 10 muestras de ambos extremos del enlace (emisor y receptor), calcula el promedio de cada métrica, clasifica la calidad de red según umbrales predefinidos, y devuelve el nivel de redundancia recomendado. El agente toma el máximo entre la recomendación del emisor y la del receptor para garantizar que el link más débil determina la protección efectiva.

### Control de acceso

Tres modalidades coexisten en el mismo despliegue. En modo desarrollo, cualquier peer se registra sin credenciales. En modo OIDC, el agente ejecuta el flujo PKCE: abre el browser del sistema para autenticación en Keycloak, recibe el código de autorización en un endpoint local, intercambia código por JWT, y usa el JWT para registrarse; el campo `iss` del JWT determina el `org_id` para aislación multi-tenant. En modo device token, el administrador genera un token de 256 bits de entropía con prefijo `rd_` desde el panel de administración; el token se configura como variable de entorno en el dispositivo headless y se usa como Bearer en cada request al servidor. La política de transferencias entrantes se controla por `INCOMING_POLICY` (allow_all / deny_all / allow_list / deny_list), sobreescribible per-peer por el administrador desde el servidor.

---

## Key Flows

### Transferencia P2P directa

```
UI / CLI          Agente A                        Servidor              Agente B
─────────         ────────                        ────────              ────────
POST /transfer/send
  file_id
  target_peer_id
                  GET /metrics/recommendation/A ─────────────────────►
                  GET /metrics/recommendation/B ─────────────────────►
                                                 ◄── rec_a, rec_b ─────
                  redundancy = max(rec_a, rec_b)
                  GET /peers/{B}               ─────────────────────►
                                               ◄── {udp_host, udp_port}
                  encode_file(bytes, redundancy)
                  POST /transfer/receive ─────────────────────────────► 202 accepted
                  UDP blocks ─────────────────────────────────────────► collect blocks
                                                                         RS decode
                                                                         verify SHA-256
                                                                         store locally
◄── {status, recovered, quality}
```

### Transferencia vía relay

```
Agente A                  Servidor               Relay C               Agente B
────────                  ────────               ───────               ────────
POST /transfer/receive ──► 503 / unreachable
GET /peers/relay ────────►
                          ◄── relay_peer: C
POST /transfer/receive (relay) ──────────────►
                                               collect blocks in RAM
                                               GET /peers/{B} ──────►
                                               POST /transfer/receive ► 202 accepted
UDP blocks ─────────────────────────────────►
                                               forward blocks ────────► RS decode
                                                                         store (status: relayed)
```

### Conmutación de transporte en runtime

La variable `TRANSPORT_MODE` puede cambiar entre `udp` y `quic` sin reiniciar el agente. El agente expone `POST /config/transport` que invoca `set_transport()` internamente; el nuevo transporte toma efecto en la siguiente transferencia. El peer actualiza su registro en el servidor con el modo activo para que la UI muestre el badge correcto. Si emisor y receptor tienen modos incompatibles, el servidor advierte en la respuesta de recomendación antes de que se inicie la transferencia.

---

## Relay System

| Tag | Comportamiento |
|---|---|
| `ephemeral` | Los bloques se mantienen solo en RAM; nunca se escriben a disco. Si el proceso relay termina antes de reenviar, la transferencia falla. |
| `restricted` | Solo reenvía a peers en una allowlist configurada explícitamente. Rechaza solicitudes de relay para destinos no autorizados. |
| `gateway` | Usa rutas estáticas (`RELAY_STATIC_ROUTES`) para resolver destinos sin consultar al servidor. Permite operación offline del relay sin TCP al servidor central. |

Un peer relay puede tener múltiples tags simultáneamente.

---

## Adaptive Redundancy

| Calidad | Pérdida | RTT | Jitter | Redundancia |
|---|---|---|---|---|
| Excellent | < 1% | < 50 ms | < 5 ms | 5% |
| Good | < 5% | < 150 ms | < 20 ms | 10% |
| Fair | < 15% | < 500 ms | < 80 ms | 25% |
| Poor | < 30% | < 1000 ms | < 200 ms | 40% |
| Critical | cualquier peor | — | — | 50% |

La recomendación se calcula muestreando **ambos extremos** del enlace en paralelo:

```
redundancy = max(
    GET /metrics/recommendation/{sender_id},
    GET /metrics/recommendation/{receiver_id}
)
```

El servidor mantiene un buffer de las últimas 10 muestras por peer en Redis. Si no hay muestras acumuladas, el fallback conservador es 25%.

---

## Authentication Modes

| Modo | Activación | Caso de uso |
|---|---|---|
| Dev (sin auth) | `OIDC_ENABLED=false` | Desarrollo local; todos los peers en org `dev` |
| OIDC + PKCE | `OIDC_ENABLED=true` + Keycloak configurado | Usuarios humanos en producción; aislación por realm |
| Device token | Token `rd_*` en `AGENT_SERVICE_TOKEN` | Dispositivos IoT/edge headless sin usuario interactivo |

Los device tokens tienen 256 bits de entropía, prefijo `rd_`, se almacenan en Redis y son revocables instantáneamente desde el panel de administración. Los tokens pueden ser temporales (TTL en días, expiración automática por Redis) o indefinidos.

---

## Daemon Service

| Plataforma | Mecanismo | Archivo de entorno |
|---|---|---|
| Linux | systemd `--user` unit | `~/.config/rockdove/agent.env` |
| macOS | LaunchAgent plist | `~/Library/LaunchAgents/com.rockdove.agent.plist` |
| Windows | `schtasks` ONLOGON task | Variables en la tarea programada |

Comandos: `rs-agent daemon install | start | stop | status | uninstall`

---

## Deployment Profiles

| Perfil | Descripción | Comando |
|---|---|---|
| Desktop (Electron) | Shell Electron lanza el agente Python y carga la React SPA. No requiere Docker en el cliente. | Ejecutable `.AppImage` / `.exe` / `.dmg` |
| Headless Docker | Agente sin UI. Recibe transferencias UDP y almacena localmente. Para IoT/edge. | `docker run -e PEER_ID=edge-01 -e SERVER_URL=... -p 9001:9001/udp rs-agent` |
| Server (Docker Compose) | Servidor + Neo4j + Redis + Keycloak (opcional). | `cd server && docker compose up --build` |

---

## Port Reference

| Componente | Puerto | Protocolo | Notas |
|---|---|---|---|
| Servidor central | 8080 | TCP | Accesible desde todos los peers (HTTPS) |
| Agente HTTP | 8000 | TCP | Solo loopback (Electron → agente local) |
| Agente UDP/QUIC | 9001 | UDP | Debe ser alcanzable entre peers; único puerto con requerimiento de firewall entre peers |
| Neo4j | 7687 | TCP (Bolt) | Solo acceso interno desde el servidor |
| Redis | 6379 | TCP | Solo acceso interno desde el servidor |
| Keycloak | 8081 | TCP | Opcional; accesible desde agentes para JWKS |

---

## Environment Variables

### Agente

| Variable | Default | Descripción |
|---|---|---|
| `SERVER_URL` | `http://localhost:8080` | URL del servidor de coordinación |
| `PEER_ID` | `default-peer` | Identificador único de este peer |
| `PEER_OWNER` | — | Agrupa visualmente peers por propietario |
| `AGENT_API_URL` | autodetectada | URL HTTP pública del agente (registrada en el servidor) |
| `UDP_PORT` | `9001` | Puerto UDP/QUIC para recibir bloques RS |
| `TRANSPORT_MODE` | `udp` | `udp` (raw socket) o `quic` (TLS 1.3, RFC 9221) |
| `STORAGE_PATH` | `~/.local/share/rockdove` | Ruta de almacenamiento local |
| `AGENT_SERVICE_TOKEN` | — | Device token `rd_*` para autenticación headless |
| `NETWORK_HINT` | `auto` | Perfil de red: `lan`, `wifi`, `cellular`, `satellite`, `auto` |
| `INCOMING_POLICY` | `allow_all` | Política de transferencias entrantes: `allow_all`, `deny_all`, `allow_list`, `deny_list` |
| `RELAY_STATIC_ROUTES` | — | Rutas estáticas para relay en modo `gateway` (JSON) |

### Servidor

| Variable | Default | Descripción |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Conexión a Redis |
| `NEO4J_URI` | `bolt://localhost:7687` | Conexión a Neo4j |
| `NEO4J_USER` | `neo4j` | Usuario Neo4j |
| `NEO4J_PASSWORD` | — | Contraseña Neo4j |
| `OIDC_ENABLED` | `false` | Activa validación JWT via Keycloak |
| `KEYCLOAK_URL` | — | URL base de Keycloak (ej. `http://keycloak:8081`) |
| `HEARTBEAT_TTL_S` | `30` | Segundos sin heartbeat antes de considerar un peer offline |
