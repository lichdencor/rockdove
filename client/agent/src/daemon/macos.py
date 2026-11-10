"""LaunchAgent plist management for the RockDove agent (macOS)."""
import plistlib
import subprocess
import sys
from pathlib import Path

_BUNDLE_ID = "io.rockdove.agent"


def _plist_path() -> Path:
    p = Path.home() / "Library" / "LaunchAgents"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{_BUNDLE_ID}.plist"


def _env_file() -> Path:
    p = Path.home() / ".config" / "rockdove"
    p.mkdir(parents=True, exist_ok=True)
    env_path = p / "agent.env"
    if not env_path.exists():
        env_path.write_text(
            "# RockDove agent environment — KEY=value pairs, one per line\n"
            "# PEER_ID=my-hostname\n"
            "# SERVER_URL=http://server:8080\n"
        )
    return env_path


def _read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _program_args() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    import shutil
    uv = shutil.which("uv") or "uv"
    src = Path(__file__).parent.parent
    return [uv, "run", "--directory", str(src.parent),
            "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


def install() -> None:
    env_file = _env_file()
    env_vars = _read_env(env_file)
    args = _program_args()

    log_dir = Path.home() / "Library" / "Logs"
    plist: dict = {
        "Label": _BUNDLE_ID,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_dir / "rockdove-agent.log"),
        "StandardErrorPath": str(log_dir / "rockdove-agent-err.log"),
    }
    if env_vars:
        plist["EnvironmentVariables"] = env_vars

    path = _plist_path()
    with open(path, "wb") as f:
        plistlib.dump(plist, f)

    subprocess.run(["launchctl", "load", str(path)], check=True)
    print(f"LaunchAgent installed: {_BUNDLE_ID}")
    print(f"Env file: {env_file}")
    print(f"Logs: {log_dir}/rockdove-agent*.log")


def start() -> None:
    subprocess.run(["launchctl", "start", _BUNDLE_ID], check=True)
    print("Agent started")


def stop() -> None:
    subprocess.run(["launchctl", "stop", _BUNDLE_ID], check=True)
    print("Agent stopped")


def status() -> None:
    result = subprocess.run(
        ["launchctl", "list", _BUNDLE_ID],
        capture_output=True, text=True,
    )
    print(result.stdout or result.stderr)


def uninstall() -> None:
    path = _plist_path()
    subprocess.run(["launchctl", "unload", str(path)], check=False)
    if path.exists():
        path.unlink()
    print(f"LaunchAgent removed: {_BUNDLE_ID}")
