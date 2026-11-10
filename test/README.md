# Laboratorio de pruebas reproducible

Levanta server + Redis + Neo4j + dos agentes (`rd-a`, `rd-b`) sin root, sin `.env` del host y sin `tc/netem`.

```bash
cd test
docker compose -f docker-compose.test.yml up -d --build --wait   # server :18080, rd-a :18001, rd-b :18002
python3 smoke.py                                                 # sube en rd-a, envía a rd-b, compara sha256
docker compose -f docker-compose.test.yml down -v
```

Perfiles opcionales:

| Perfil | Qué agrega | Cómo usarlo |
|--------|-----------|-------------|
| `loss` | Proxy UDP con pérdida/retardo delante de rd-b | `TEST_AGENT_B_UDP_HOST=udp-proxy TEST_LOSS_PCT=15 docker compose -f docker-compose.test.yml --profile loss up -d --wait`; control en `:18300/set?loss=40&delay=80&jitter=20`, `/stats`, `/reset` |
| `auth` | Keycloak con el realm `rockdove` (`:18081`) | `TEST_OIDC_ENABLED=true ... --profile auth up -d` |

Puertos y credenciales se cambian con variables `TEST_*` (ver el compose).

## Ayudas de testabilidad

- **Logs JSON** (server y agente): `ts`, `level`, `logger`, `msg` y por request `method`, `path`, `status`, `duration_ms`, `client_ip`, `user`. Los rechazos de auth salen como `auth_denied`. Variables `LOG_LEVEL` y `LOG_FORMAT=json|text`.
- **`data-testid`** en los controles de la UI (`nav-*`, `server-connect`, `sso-login`, `transfer-send`, `file-send-<id>`, `cfg-*`, etc.).
- **Electron sin ventana**: `electron . --headless-test` (o `ROCKDOVE_HEADLESS_TEST=1`) carga la UI oculta y se maneja con `--remote-debugging-port`. El agente corre en su propio grupo de procesos, se mata al salir y además se autocierra si desaparece el padre (`AGENT_PARENT_PID`).
- **Agente sin Electron**: `POST /auth/token` con `{"token", "server_url"}` ya reemplaza el login del navegador; con `AGENT_SERVICE_TOKEN` el agente headless se registra solo.
- **Agente endurecido (opcional)**: `AGENT_API_TOKEN` exige bearer en `/files`, `/config`, `/auth/token` y `/transfer/send`; `MAX_UPLOAD_BYTES` limita subidas (413). Las rutas entre peers quedan abiertas.
- **Exportación de métricas**: `GET /metrics/export?format=csv|json[&peer_id=...]` en el server.
