"""Daemon subcommand dispatcher: rs-agent daemon <install|start|stop|status|uninstall>"""
import sys


_CMDS = ["install", "start", "stop", "status", "uninstall"]


def daemon_main(args: list[str] | None = None) -> None:
    argv = args if args is not None else sys.argv[2:]

    if not argv or argv[0] not in _CMDS:
        print(f"Usage: rs-agent daemon <{'|'.join(_CMDS)}>")
        sys.exit(1)

    cmd = argv[0]

    if sys.platform.startswith("linux"):
        from daemon.linux import install, start, stop, status, uninstall
    elif sys.platform == "darwin":
        from daemon.macos import install, start, stop, status, uninstall
    elif sys.platform == "win32":
        from daemon.windows import install, start, stop, status, uninstall
    else:
        print(f"Unsupported platform: {sys.platform}", file=sys.stderr)
        sys.exit(1)

    dispatch = {
        "install": install,
        "start": start,
        "stop": stop,
        "status": status,
        "uninstall": uninstall,
    }

    try:
        dispatch[cmd]()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
