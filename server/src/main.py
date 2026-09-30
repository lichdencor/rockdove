from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from device_tokens.router import router as device_tokens_router
from invites.router import router as invites_router
from jev.router import router as jev_router
from metrics.router import router as metrics_router
from peers.router import router as peers_router

app = FastAPI(title="RS Transfer Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(peers_router, prefix="/peers", tags=["peers"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(invites_router, prefix="/invites", tags=["invites"])
app.include_router(device_tokens_router, prefix="/device-tokens", tags=["device-tokens"])
app.include_router(jev_router, prefix="/jev", tags=["jev"])


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/config", tags=["auth"])
async def auth_config() -> dict:
    settings = get_settings()
    public_issuer = settings.OIDC_ISSUER_PUBLIC or settings.OIDC_ISSUER or None
    return {
        "oidc_enabled": settings.OIDC_ENABLED,
        "issuer": public_issuer if settings.OIDC_ENABLED else None,
        "client_id": settings.OIDC_CLIENT_ID if settings.OIDC_ENABLED else None,
    }
