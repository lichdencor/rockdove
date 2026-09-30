"""Systemd user service management for the RockDove agent (Linux)."""
import os
import subprocess
import sys
from pathlib import Path

_SERVICE_NAME = "rockdove-agent"
_UNIT_LABEL = f"{_SERVICE_NAME}.service"


def _unit_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    p = base / "systemd" / "user"
    p.mkdir(parents=True, exist_ok=True)
    return p / _UNIT_LABEL


def _env_file() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    p = base / "rockdove"
    p.mkdir(parents=True, exist_ok=True)
    env_path = p / "agent.env"
    if not env_path.exists():
        env_path.write_text(
            "# RockDove agent environment — uncomment and set values\n"
            "# PEER_ID=my-hostname\n"
            "# SERVER_URL=http://server:8080\n"
            "# AGENT_PORT=8000\n"
            "# UDP_PORT=9001\n"
        )
    return env_path


def _exec_start() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    import shutil
    uv = shutil.which("uv") or "uv"
    # Point at the src/ directory of the checked-out repo
    src = Path(__file__).parent.parent
    return (
        f"{uv} run --directory {src.parent} uvicorn main:app"
        " --host 0.0.0.0 --port ${AGENT_PORT:-8000}"
    )


def install() -> None:
    env_file = _env_file()
    exec_start = _exec_start()

    unit = (
        "[Unit]\n"
        "Description=RockDove RS Transfer Agent\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        f"EnvironmentFile=-{env_file}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )

    path = _unit_path()
    path.write_text(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", _UNIT_LABEL], check=True)
    print(f"Service installed: {_UNIT_LABEL}")
    print(f"Env file: {env_file}")
    print("Run: rs-agent daemon start")


def start() -> None:
    subprocess.run(["systemctl", "--user", "start", _UNIT_LABEL], check=True)
    print("Agent started")


def stop() -> None:
    subprocess.run(["systemctl", "--user", "stop", _UNIT_LABEL], check=True)
    print("Agent stopped")


def status() -> None:
    subprocess.run(["systemctl", "--user", "status", _UNIT_LABEL])


def uninstall() -> None:
    subprocess.run(["systemctl", "--user", "stop", _UNIT_LABEL], check=False)
    subprocess.run(["systemctl", "--user", "disable", _UNIT_LABEL], check=False)
    path = _unit_path()
    if path.exists():
        path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print(f"Service removed: {_UNIT_LABEL}")
