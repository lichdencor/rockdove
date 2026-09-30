"""Windows Task Scheduler management for the RockDove agent."""
import os
import subprocess
import sys
from pathlib import Path

_TASK_NAME = "RockDoveAgent"


def _env_file() -> Path:
    appdata = Path(os.environ.get("APPDATA", "")) or Path.home() / "AppData" / "Roaming"
    p = appdata / "RockDove"
    p.mkdir(parents=True, exist_ok=True)
    env_path = p / "agent.env"
    if not env_path.exists():
        env_path.write_text(
            "# RockDove agent environment — set as system/user env vars\r\n"
            "# or edit this file and restart the task.\r\n"
            "# PEER_ID=my-hostname\r\n"
            "# SERVER_URL=http://server:8080\r\n"
        )
    return env_path


def _exec_cmd() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    import shutil
    uv = shutil.which("uv") or "uv"
    src = Path(__file__).parent.parent
    return (
        f'"{uv}" run --directory "{src.parent}"'
        ' uvicorn main:app --host 0.0.0.0 --port 8000'
    )


def install() -> None:
    env_file = _env_file()
    exec_cmd = _exec_cmd()
    subprocess.run(
        ["schtasks", "/create", "/f",
         "/tn", _TASK_NAME,
         "/tr", exec_cmd,
         "/sc", "ONLOGON",
         "/rl", "LIMITED"],
        check=True,
    )
    print(f"Task installed: {_TASK_NAME}")
    print(f"Env file (reference): {env_file}")
    print("Set env vars in System Properties > Environment Variables.")


def start() -> None:
    subprocess.run(["schtasks", "/run", "/tn", _TASK_NAME], check=True)
    print("Agent started")


def stop() -> None:
    subprocess.run(["schtasks", "/end", "/tn", _TASK_NAME], check=True)
    print("Agent stopped")


def status() -> None:
    subprocess.run(["schtasks", "/query", "/tn", _TASK_NAME, "/fo", "LIST"])


def uninstall() -> None:
    subprocess.run(["schtasks", "/delete", "/f", "/tn", _TASK_NAME], check=False)
    print(f"Task removed: {_TASK_NAME}")
