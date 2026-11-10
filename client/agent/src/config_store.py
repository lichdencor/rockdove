from __future__ import annotations

import json
import os
from pathlib import Path

_KNOWN_KEYS: frozenset[str] = frozenset({
    "server_url",
    "peer_id",
    "agent_api_url",
    "udp_host",
    "udp_port",
    "udp_advertise_host",
    "transport_mode",
    "storage_path",
    "invite_token",
    "network_hint",
})

_store: dict = {}


def _config_path() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "rockdove" / "agent_config.json"


def load(defaults: dict) -> None:
    """Seed from defaults dict, then overlay with on-disk JSON values."""
    global _store
    _store = {k: v for k, v in defaults.items() if k in _KNOWN_KEYS}
    path = _config_path()
    if path.exists():
        try:
            on_disk: dict = json.loads(path.read_text())
            for k, v in on_disk.items():
                if k in _KNOWN_KEYS:
                    _store[k] = v
        except Exception:
            pass


def save() -> None:
    """Write current store to disk (creates parent dirs if needed)."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_store, indent=2))


def get(key: str, default=None):
    """Return stored value or default."""
    return _store.get(key, default)


def update(values: dict) -> None:
    """Update multiple keys at once (only known keys)."""
    for k, v in values.items():
        if k in _KNOWN_KEYS:
            _store[k] = v


def get_all() -> dict:
    """Return copy of entire store."""
    return dict(_store)
