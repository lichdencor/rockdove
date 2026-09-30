# RS Transfer Server

Central control plane for the RockDove P2P network. Manages peer registration, real-time discovery, network quality metrics, invite tokens, org-level isolation, and (optionally) Keycloak OIDC.

## Stack

| Layer | Tech |
|---|---|
| Runtime | Python 3.12, FastAPI, uvicorn |
| Persistence | Redis 7 (hashes + lists + TTL) |
| Auth | PyJWT (HS256 invites, RS256 Keycloak JWTs) |
| Container | Docker Compose (server + Redis + Keycloak) |

## Quick start

```bash
# 1. Copy and fill the env file (repo root)
cp .env.example .env

# 2. Start all services
cd server
docker compose up --build

# Server   → http://localhost:8080
# Keycloak → http://localhost:8081  (admin/admin)
# Redis    → localhost:6379
```

Dev without Docker:

```bash
uv sync
REDIS_URL=redis://localhost:6379/0 uv run uvicorn main:app --reload --app-dir src
```

## API surface

```
GET  /health                             liveness probe
GET  /auth/config                        OIDC config for the UI

POST /peers/register                     register or re-register a peer
POST /peers/{peer_id}/heartbeat          refresh TTL (keep-alive)
GET  /peers/                             list online peers (filtered by caller's scope)
GET  /peers/{peer_id}                    get a single peer
WS   /peers/watch?token=<jwt>            real-time peer list stream

POST /metrics/report                     ingest a MetricReport from an agent
GET  /metrics/recommendation/{peer_id}  compute redundancy recommendation

GET  /jev/status                         Jev availability + config
GET  /jev/transit/{source}/{target}     redundancy degree + relay decision
POST /jev/mock/seed[/{scenario}]         seed mock metrics between two hosts

POST /invites/                           create a single-use invite token
```

Interactive docs at `/docs` when running.

## Source layout

```
src/
├── main.py              app factory, CORS, router mounting, /health, /auth/config
├── config.py            Settings (pydantic-settings, all env vars)
├── redis_client.py      shared async Redis connection pool
│
├── auth/
│   ├── deps.py          extract_auth() FastAPI dependency
│   └── verifier.py      PyJWKClient JWKS cache + verify_token()
│
├── peers/
│   └── router.py        registration, heartbeat, list, WebSocket watch
│
├── metrics/
│   ├── models.py        MetricReport, RecommendationResponse
│   ├── collector.py     Redis LPUSH/LTRIM sliding window (10 samples/peer)
│   ├── recommender.py   quality bands + network profile floors → redundancy level
│   └── router.py        /report and /recommendation/{peer_id} endpoints
│
├── jev/
│   ├── client.py        async httpx client for OpenRouter Decisions API
│   ├── decider.py       build state+questions, call Jev, confidence gate + fallback
│   ├── mock.py          seed telemetry between two hosts + relays (dev)
│   └── router.py        /status, /transit/{source}/{target}, /mock/seed
│
└── invites/
    ├── models.py        InviteCreate, InviteInfo
    └── router.py        JWT creation, Redis state machine, validate_invite()
```

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `HEARTBEAT_TTL_S` | `30` | Seconds before an unresponsive peer is evicted |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `OIDC_ENABLED` | `false` | Set to `true` to require auth |
| `OIDC_ISSUER` | `` | Public issuer URL for JWT `iss` claim validation (sent to the UI as well) |
| `OIDC_KEYCLOAK_URL` | `` | Internal Keycloak base URL for JWKS fetch (Docker: `http://keycloak:8080`) |
| `OIDC_ISSUER_PUBLIC` | `` | Override for the public issuer URL sent to the UI (proxy scenarios) |
| `OIDC_CLIENT_ID` | `` | Keycloak client ID |
| `OIDC_ADMIN_GROUP` | `admin` | Group name whose members have admin privileges |
| `INVITE_SECRET` | `change-me-in-production` | HS256 key for invite JWTs |
| `AGENT_SERVICE_TOKEN` | `` | Static Bearer token for headless service agents |
| `JEV_ENABLED` | `false` | Enable the Jev AI-driven redundancy/relay decisions |
| `JEV_MODEL` | `typesafe/jev-1.13` | Jev model id served through OpenRouter |
| `OPENROUTER_API_KEY` | `` | OpenRouter API key (server-side) for Jev |
| `JEV_CONFIDENCE_THRESHOLD` | `0.85` | Above this confidence Jev's answer is used; below it falls back to the deterministic table |

### Docker networking and OIDC_KEYCLOAK_URL

When running inside Docker Compose, the server container cannot reach the host's `localhost:8081` to fetch Keycloak's JWKS endpoint — `localhost` inside a container refers to the container itself. Set `OIDC_KEYCLOAK_URL=http://keycloak:8080` so the server resolves Keycloak through Docker's internal network. `OIDC_ISSUER` must remain the public URL (`http://localhost:8081/realms/rockdove`) because that is the value Keycloak stamps into the `iss` claim, and the two must match for token validation to pass.

```yaml
# docker-compose.yml (excerpt)
server:
  environment:
    OIDC_ISSUER: http://localhost:8081/realms/rockdove      # public — matches iss claim
    OIDC_KEYCLOAK_URL: http://keycloak:8080                 # internal — used for JWKS fetch
```

## Auth modes

### 1. Dev mode (`OIDC_ENABLED=false`)

No authentication is required. The peer ID is taken directly from the request body. Use this mode for local development and unit tests only — do not expose it externally.

### 2. OIDC mode (`OIDC_ENABLED=true`)

Every protected endpoint requires an `Authorization: Bearer <token>` header. The server accepts three token types:

**Keycloak JWT**
The standard path for human users and Electron clients. The token is issued by Keycloak after PKCE login. The server validates the RS256 signature via the JWKS endpoint derived from `OIDC_KEYCLOAK_URL`, then extracts:
- `sub` — used as `peer_id` for registration
- `realm_name` (from the issuer URL path) — used as `org_id`
- `groups` claim — first element is the peer's group

**Service token (`AGENT_SERVICE_TOKEN`)**
A static shared secret configured via env var. When the bearer token matches `AGENT_SERVICE_TOKEN`, the request is trusted and the body `peer_id` is used as-is. The `org_id` is derived from `OIDC_ISSUER` (the realm portion of the issuer URL), not hardcoded. Use this for automated agents that cannot perform interactive OIDC login.

**Invite token (`INVITE_TOKEN`)**
A single-use HS256 JWT created by `POST /invites/`. On registration, the agent passes the token in the `invite_token` field of the request body. The server validates the token, atomically marks it as used in Redis, and completes registration. The token's embedded `org_id` always matches the org of the admin who created the invite — it cannot be transferred across orgs.

## Org isolation and group scopes

### Org = Keycloak realm

Each Keycloak realm is an independent organization. Peers registered under different realms are completely isolated — `GET /peers/` never returns peers from another org, even if a request is correctly authenticated.

Redis keys are namespaced by org:

```
peer:{org_id}:{peer_id}    hash — peer registration data
scope:{org_id}             string — JSON scope config for the org
```

For example, peers in the `acme` realm are stored as `peer:acme:peer-alice` and are invisible to any request authenticated against the `umbrella` realm.

### Group scopes

Within an org, visibility between peers is controlled by a scope configuration stored at `scope:{org_id}`. The value is a JSON object mapping group names to lists of groups that members of that group can see:

```json
{
  "engineering": ["engineering", "ops"],
  "sales": ["sales"],
  "ops": ["ops", "engineering", "sales"]
}
```

The special value `__all__` in a group's list grants full-org visibility (the group sees all other peers in the org regardless of their group):

```json
{
  "admin": ["__all__"],
  "engineering": ["engineering"]
}
```

Scope configuration is updated at runtime via the admin panel — no server restart required.

**Default behavior:** If no scope config exists for an org, a peer can only see other peers in the same group.

### Admin bypass

A peer whose JWT contains the group defined in `OIDC_ADMIN_GROUP` (default: `admin`) bypasses all scope checks and sees every online peer in the org. Admin status does not grant cross-org visibility.

## Peer registration data model

Redis hash key: `peer:{org_id}:{peer_id}`

| Field | Example |
|---|---|
| `peer_id` | `peer-alice` |
| `org_id` | `rockdove` |
| `group` | `engineering` |
| `api_url` | `http://192.168.1.10:8000` |
| `udp_host` | `192.168.1.10` |
| `udp_port` | `9001` |
| `last_seen` | ISO-8601 UTC |
| `network_hint` | `wifi` / `lan` / `cellular` / `satellite` / `auto` |

The key expires after `HEARTBEAT_TTL_S` seconds. Expiry equals peer offline — no explicit deregistration is required.

## Invite tokens for headless agents

The invite system lets admins provision IoT devices, edge nodes, and CI agents without interactive OIDC login.

**Creating an invite:**

```bash
curl -X POST http://localhost:8080/invites/ \
  -H "Authorization: Bearer <admin_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"peer_id": "sensor-planta-1", "group": "sensors"}'
```

Response:

```json
{
  "token": "eyJ...",
  "peer_id": "sensor-planta-1",
  "org_id": "rockdove",
  "expires_at": "2025-06-01T00:00:00Z"
}
```

- In OIDC mode, the invite's `org_id` is always the caller's org (derived from their realm). It cannot be set to an arbitrary value.
- The token is single-use. Redis tracks state as `pending → used`. A second registration attempt with the same token is rejected with `409 Conflict`.
- `POST /invites/` requires authentication (admin or service token).

**Using the invite on a headless device:**

```dotenv
SERVER_URL=http://mi-servidor:8080
PEER_ID=sensor-planta-1
INVITE_TOKEN=eyJ...
UDP_HOST=0.0.0.0
UDP_PORT=9001
```

The agent reads `INVITE_TOKEN` at startup and sends it in the `invite_token` field of the registration request. After successful registration, the token is consumed and cannot be reused.

## WebSocket: real-time peer list

```
WS /peers/watch?token=<jwt>
```

Streams peer list changes as JSON events. In OIDC mode, pass the Keycloak JWT as the `token` query parameter — WebSocket connections cannot send custom headers in browser environments, so query-param auth is used instead of `Authorization: Bearer`.

Each message is a full peer list snapshot filtered by the caller's scope:

```json
{
  "event": "peer_list",
  "peers": [
    {
      "peer_id": "peer-bob",
      "api_url": "http://192.168.1.11:8000",
      "udp_host": "192.168.1.11",
      "udp_port": 9001,
      "network_hint": "lan"
    }
  ]
}
```

## Network profiles

The recommender maps averaged RTT, jitter, and loss to a quality band, then enforces a minimum redundancy floor based on the declared network type:

| Profile (`network_hint`) | Min redundancy |
|---|---|
| `lan` | 5% |
| `wifi` | 10% |
| `cellular` | 20% |
| `satellite` | 35% |
| `auto` | no floor (quality band only) |

## Keycloak setup

The pre-configured realm is imported automatically on first container start from `keycloak/rockdove-realm.json`.

**Realm defaults:**
- Realm: `rockdove`
- Client: `rockdove-client` (public client, PKCE S256)
- Redirect URIs: `http://localhost:5173/*`, `http://localhost:5174/*`
- Test user: `dev-user` / `password123` assigned to the `/admin` group

**Required realm configuration (already applied in the exported JSON):**

The `groups` claim must be present in the access token. If you are configuring a realm manually or the exported JSON is stale, add the following protocol mapper to `rockdove-client`:

| Setting | Value |
|---|---|
| Mapper type | `oidc-group-membership-mapper` |
| Name | `groups` |
| Token Claim Name | `groups` |
| Full group path | `OFF` (set `full.path=false`) |
| Add to access token | `ON` |
| Add to ID token | `ON` |

Without this mapper, the server cannot determine a peer's group and will deny registration.

**Admin group:**
The `admin` group must exist in the realm. `dev-user` is pre-assigned to `/admin`. Any user you want to have admin privileges must be added to this group in the Keycloak admin console.

**If Keycloak was already running before the realm JSON was updated:**

Realm import only runs on a fresh volume. To apply changes to an existing instance either restart the container with a clean volume (`docker compose down -v && docker compose up --build`) or apply the changes manually via the Keycloak admin console at `http://localhost:8081`.
