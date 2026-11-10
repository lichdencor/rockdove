# RockDove

RockDove is a P2P file transfer system that uses Reed-Solomon Forward Error Correction (FEC) over raw UDP to survive packet loss without retransmission. Peers discover each other through a central FastAPI control-plane server, but data flows directly machine-to-machine — the server never touches file content. Authentication and identity are handled by Keycloak OIDC; each Keycloak realm is an isolated organization, so peers in different realms cannot see or reach each other. Group visibility within an org is configurable by admins at runtime.

## Requisitos

| Componente | Version minima | Para qué |
|---|---|---|
| Docker + Docker Compose | Docker 24 / Compose v2 | Levantar el stack del servidor |
| Node.js + npm | Node 20 / npm 10 | Electron app y UI |
| Python + uv | Python 3.12 / uv 0.4+ | Agente y tests |

## Estructura del repositorio

```
reed-solomon_RD-II/
├── server/          Control plane (FastAPI + Redis + Keycloak)
├── client/
│   ├── electron/    Electron shell (main.ts, preload.ts)
│   ├── ui/          React SPA (Vite)
│   └── agent/       Python data-plane agent
├── docs/            Architecture, RS spec, rules
└── .env             Root env file (shared by server docker-compose and agent)
```

## Inicio rapido

### 1. Configurar el .env

```bash
cp .env.example .env   # si existe; si no, crear el archivo con los valores de abajo
```

Contenido minimo del `.env`:

```dotenv
# Server
OIDC_ENABLED=true
OIDC_ISSUER=http://localhost:8081/realms/rockdove
OIDC_CLIENT_ID=rockdove-client

# Agent (one .env per peer)
SERVER_URL=http://localhost:8080
PEER_ID=peer-alice
UDP_HOST=0.0.0.0
UDP_PORT=9001
# TRANSPORT_MODE=udp  # o quic para TLS 1.3
```

### 2. Levantar el stack del servidor

```bash
cd server
docker compose up --build
```

Esto inicia tres servicios:

- **Server** — http://localhost:8080 (FastAPI; documentacion interactiva en `/docs`)
- **Keycloak** — http://localhost:8081 (credenciales: `admin` / `admin`)
- **Redis** — localhost:6379

El primer arranque importa automaticamente el realm `rockdove`. Incluye el usuario de prueba `dev-user` / `password123` asignado al grupo `admin`.

> **Nota Docker:** `OIDC_KEYCLOAK_URL: http://keycloak:8080` esta definido en el docker-compose para que el contenedor del servidor pueda alcanzar Keycloak via la red interna de Docker durante la verificacion de JWKS. La variable `OIDC_ISSUER` se mantiene como la URL publica (`http://localhost:8081/...`) porque debe coincidir con el claim `iss` de los tokens.

### 3. Construir y ejecutar el cliente (Electron AppImage)

```bash
cd client

# Instalar dependencias Node
npm install

# Construir el agente Python embebido (requiere uv)
./scripts/build-agent.sh

# Construir el AppImage completo
npm run dist:local
```

Ejecutar la aplicacion:

```bash
./dist/app/RockDove-0.1.0.AppImage
```

#### Modo desarrollo (sin AppImage)

```bash
# Terminal 1 — UI dev server
cd client/ui && npm run dev

# Terminal 2 — Electron shell + agente
cd client && npm run dev
```

### 4. Primer login

1. En la pantalla de conexion, ingresar `http://localhost:8080` como server URL.
2. Hacer click en **Iniciar sesion con SSO** — se abre el navegador del sistema con la pagina de Keycloak.
3. Ingresar credenciales: `dev-user` / `password123`.
4. Al volver a la app, el agente recibe el JWT y se registra automaticamente con el servidor.

### 5. Panel de administracion

`dev-user` pertenece al grupo `admin`. Despues del login aparece el boton **Admin** en el header con dos pestanas:

- **Visibilidad de grupos** — define que grupos pueden verse entre si dentro de la org. Usar el valor especial `__all__` para permitir visibilidad total entre todos los grupos.
- **Invites para dispositivos** — genera tokens de un solo uso para agentes headless (IoT, edge, CI). El resultado es un snippet `.env` listo para copiar.

## Agente headless (IoT / edge)

Para dispositivos sin UI, generar un invite token desde el panel de admin y crear un `.env`:

```dotenv
SERVER_URL=http://mi-servidor:8080
PEER_ID=sensor-planta-1
INVITE_TOKEN=eyJ...     # token de un solo uso — se consume al registrarse
UDP_HOST=0.0.0.0
UDP_PORT=9001
```

Ejecutar el agente directamente:

```bash
cd client/agent
uv sync
uv run uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000
```

O via Docker si se construyo la imagen del agente:

```bash
docker run --env-file .env -p 8000:8000 -p 9001:9001/udp rs-agent
```

## Variables de entorno (referencia completa)

### Server

| Variable | Default | Descripcion |
|---|---|---|
| `OIDC_ENABLED` | `false` | `true` para requerir autenticacion |
| `OIDC_ISSUER` | `` | URL publica del issuer Keycloak (para validar el claim `iss`) |
| `OIDC_KEYCLOAK_URL` | `` | URL interna de Keycloak (Docker: `http://keycloak:8080`) |
| `OIDC_CLIENT_ID` | `` | Client ID en Keycloak |
| `OIDC_ADMIN_GROUP` | `admin` | Nombre del grupo con privilegios de admin |
| `HEARTBEAT_TTL_S` | `30` | Segundos hasta considerar un peer offline |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `INVITE_SECRET` | `change-me-in-production` | Clave HS256 para firmar invite tokens |
| `AGENT_SERVICE_TOKEN` | `` | Bearer token estatico para agentes de servicio |

### Agent

| Variable | Default | Descripcion |
|---|---|---|
| `SERVER_URL` | `http://localhost:8080` | Direccion del servidor central |
| `PEER_ID` | `default-peer` | Identificador unico de este peer |
| `AGENT_API_URL` | auto-detectado | URL publica del agente (anunciada a otros peers) |
| `AGENT_PORT` | `8000` | Puerto HTTP del agente |
| `UDP_HOST` | `0.0.0.0` | Direccion de escucha UDP |
| `UDP_PORT` | `9001` | Puerto UDP para transferencias RS |
| `TRANSPORT_MODE` | `udp` | Protocolo de transporte: `udp` = socket raw, `quic` = aioquic con TLS 1.3 |
| `STORAGE_PATH` | `~/.local/share/rockdove` | Directorio para archivos almacenados |
| `NETWORK_HINT` | `auto` | `lan` / `wifi` / `cellular` / `satellite` |
| `AGENT_SERVICE_TOKEN` | `` | Token de servicio (alternativa al login OIDC) |
| `INVITE_TOKEN` | `` | Token de invitacion de un solo uso (headless) |

## Modelo de autorizacion

- **Org** = Keycloak realm. Los peers estan aislados por org; un peer en el realm `acme` nunca ve peers del realm `umbrella`.
- **Groups** = grupos dentro del realm. El primer grupo del claim `groups` del JWT es el grupo del peer.
- **Scopes** = regla de visibilidad `{grupo: [grupos_visibles]}` almacenada en Redis bajo la clave `scope:{org_id}`. Configurable desde el panel de admin sin reiniciar el servidor.
- El valor especial `__all__` en la lista de grupos visibles otorga visibilidad total dentro de la org.
- **Admin** = miembro del grupo definido en `OIDC_ADMIN_GROUP` (por defecto `admin`). Bypasea todas las reglas de scope y ve todos los peers de la org.

## Flujo de transferencia

```
Sender Agent                      Receiver Agent
────────────                      ──────────────
encode_file() → n bloques RS
POST /transfer/receive ──────────►
UDP packets (n bloques) ─────────►
                                  decode_transfer()
                                  verificar SHA-256
poll GET /transfer/{id}/status ──►
◄── {status: ok | degraded | failed}
```

El servidor central no interviene en la transferencia. Solo provee el directorio de peers y la verificacion de identidad.

### Variante QUIC

Cuando `TRANSPORT_MODE=quic` (variable de entorno del agente), el transport layer usa **aioquic** sobre el mismo puerto UDP. Antes de los bloques RS, el sender emite un datagrama **CERT_HELLO** con su `peer_id` y el SHA-256 de su certificado TLS autogenerado (`CN = rockdove-{PEER_ID}`). El receiver registra la conexion como pendiente y muestra un banner en la UI con los datos del cert. El operador puede **Aceptar** o **Rechazar** la conexion; si no responde en 30 s, se acepta automaticamente.

Endpoints relevantes:
- `GET /transfer/incoming` — lista conexiones QUIC entrantes pendientes
- `POST /transfer/incoming/{transfer_id}/accept` — aprueba
- `POST /transfer/incoming/{transfer_id}/reject` — rechaza y descarta los buffers

Los certificados (RSA-2048, auto-firmados) se generan al primer arranque en `STORAGE_PATH/quic_cert.pem` y se regeneran automaticamente si `PEER_ID` cambia.

## Tests

```bash
# Agent (Python)
cd client/agent && uv run pytest -v

# UI (TypeScript)
cd client/ui && npm test

# Electron shell
cd client && npm test
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) corre en cada push:

| Job | Que hace |
|---|---|
| `test-agent` | pytest sobre el agente Python |
| `test-ui` | vitest sobre la UI React |
| `test-electron` | tsc + vitest sobre el shell Electron |
| `build-agent` | Binario PyInstaller (solo en push) |
| `build-ui` | Build de produccion Vite (solo en push) |
| `build-server` | Imagen Docker del servidor; verifica que no se incluyan fuentes `.py` en la imagen final (solo en push) |
