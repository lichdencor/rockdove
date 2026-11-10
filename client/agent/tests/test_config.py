"""
Tests for auto-IP detection and settings validation in config.py.
"""
import pytest


def test_agent_api_url_auto_detected_when_empty(monkeypatch):
    monkeypatch.setenv("AGENT_API_URL", "")
    from config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.AGENT_API_URL.startswith("http://")
    # Must contain a real IP or fallback — never just "http://"
    host = s.AGENT_API_URL.split("://")[1].split(":")[0]
    assert len(host) > 0 and host != ""


def test_agent_api_url_explicit_is_respected(monkeypatch):
    monkeypatch.setenv("AGENT_API_URL", "http://10.0.0.1:9000")
    from config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.AGENT_API_URL == "http://10.0.0.1:9000"


def test_agent_port_affects_auto_url(monkeypatch):
    monkeypatch.setenv("AGENT_API_URL", "")
    monkeypatch.setenv("AGENT_PORT", "9999")
    from config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert ":9999" in s.AGENT_API_URL


def test_defaults(monkeypatch):
    monkeypatch.delenv("AGENT_API_URL", raising=False)
    monkeypatch.delenv("AGENT_PORT", raising=False)
    from config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.AGENT_PORT == 8000
    assert s.UDP_PORT == 9001
    assert s.PEER_ID == "default-peer"


def test_transport_mode_defaults_to_udp(monkeypatch):
    monkeypatch.delenv("TRANSPORT_MODE", raising=False)
    from config import get_settings
    get_settings.cache_clear()
    assert get_settings().TRANSPORT_MODE == "udp"


def test_transport_mode_quic_accepted(monkeypatch):
    monkeypatch.setenv("TRANSPORT_MODE", "quic")
    from config import get_settings
    get_settings.cache_clear()
    assert get_settings().TRANSPORT_MODE == "quic"


def test_transport_mode_invalid_raises(monkeypatch):
    import pydantic
    monkeypatch.setenv("TRANSPORT_MODE", "tcp")
    from config import get_settings
    get_settings.cache_clear()
    with pytest.raises((pydantic.ValidationError, Exception)):
        get_settings()
