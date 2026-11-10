"""
Runtime token store — holds the JWT the UI pushes after OIDC login.
Also tracks the peer_id assigned by the server after registration,
and the active transport mode when it has been switched at runtime.
"""

_token: str = ""
_peer_id: str = ""
_server_url: str = ""
_transport_mode: str = ""


def get_token() -> str:
    return _token


def set_token(token: str) -> None:
    global _token
    _token = token


def get_peer_id() -> str:
    return _peer_id


def set_peer_id(pid: str) -> None:
    global _peer_id
    _peer_id = pid


def get_server_url() -> str:
    return _server_url


def set_server_url(url: str) -> None:
    global _server_url
    _server_url = url


def get_transport_mode() -> str:
    return _transport_mode


def set_transport_mode(mode: str) -> None:
    global _transport_mode
    _transport_mode = mode
