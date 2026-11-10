"""
PyInstaller entry point for the frozen agent binary.
"""
import os
import sys
import uvicorn

if not getattr(sys, 'frozen', False):
    # Dev mode: add src/ to path so flat imports (import main, import config, …) work
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(base_dir, "src"))

import main
app = main.app

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        from daemon.cli import daemon_main
        daemon_main()
        sys.exit(0)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("AGENT_PORT", "8000")),
        loop="asyncio",
        http="h11",
        log_level="info",
    )
