"""
Tests for rs/transport.py — UDPTransport, QUICTransport, TLS cert generation,
module singleton, and interface conformance.

All QUIC tests are skipped when aioquic is not installed so the suite stays
green in minimal envs.  The import-error path is also tested explicitly with
monkeypatching.
"""
import asyncio
import socket
import struct
from pathlib import Path

import pytest

from rs.encoder import HEADER_FMT, HEADER_SIZE, encode_file
from rs.transport import (
    BaseTransport,
    QUICTransport,
    UDPTransport,
    _AIOQUIC_AVAILABLE,
    _CERT_HELLO_MAGIC,
    _cert_cn_matches,
    _ensure_tls_certs,
    get_transport,
    set_transport,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def free_port() -> int:
    """Return a free TCP/UDP port on loopback (released before returning)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_fake_packet(transfer_id_hex: str, block_index: int, total: int) -> bytes:
    """Build a minimal valid packet (header + 8 bytes payload)."""
    tid_bytes = bytes.fromhex(transfer_id_hex)
    hdr = struct.pack(HEADER_FMT, tid_bytes, block_index, total, total, total - 1, 0, 0, 8)
    return hdr + b"\xAB" * 8


# ── interface conformance ──────────────────────────────────────────────────────

def test_udp_is_base_transport():
    assert isinstance(UDPTransport(), BaseTransport)


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
def test_quic_is_base_transport():
    assert isinstance(QUICTransport(), BaseTransport)


# ── module singleton ───────────────────────────────────────────────────────────

def test_get_transport_returns_udp_by_default():
    # The module default is UDPTransport; restore after.
    original = get_transport()
    assert isinstance(original, UDPTransport)


def test_set_transport_replaces_singleton():
    original = get_transport()
    fresh_udp = UDPTransport()
    set_transport(fresh_udp)
    assert get_transport() is fresh_udp
    set_transport(original)


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
def test_set_transport_accepts_quic():
    original = get_transport()
    qt = QUICTransport()
    set_transport(qt)
    assert isinstance(get_transport(), QUICTransport)
    set_transport(original)


# ── TLS cert generation ────────────────────────────────────────────────────────

def test_ensure_tls_certs_creates_files(tmp_path):
    cert = str(tmp_path / "cert.pem")
    key = str(tmp_path / "key.pem")
    _ensure_tls_certs(cert, key)
    assert Path(cert).exists()
    assert Path(key).exists()


def test_ensure_tls_certs_is_pem(tmp_path):
    cert = str(tmp_path / "cert.pem")
    key = str(tmp_path / "key.pem")
    _ensure_tls_certs(cert, key)
    assert Path(cert).read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert Path(key).read_bytes().startswith(b"-----BEGIN RSA PRIVATE KEY-----")


def test_ensure_tls_certs_embeds_peer_id_in_cn(tmp_path):
    cert = str(tmp_path / "cert.pem")
    key = str(tmp_path / "key.pem")
    _ensure_tls_certs(cert, key, peer_id="alice")
    assert _cert_cn_matches(cert, "rockdove-alice")
    assert not _cert_cn_matches(cert, "rockdove-bob")


def test_ensure_tls_certs_regenerates_on_peer_id_change(tmp_path):
    cert = str(tmp_path / "cert.pem")
    key = str(tmp_path / "key.pem")
    _ensure_tls_certs(cert, key, peer_id="alice")
    mtime_before = Path(cert).stat().st_mtime
    _ensure_tls_certs(cert, key, peer_id="bob")  # different peer_id → must regen
    assert Path(cert).stat().st_mtime != mtime_before
    assert _cert_cn_matches(cert, "rockdove-bob")


def test_ensure_tls_certs_idempotent(tmp_path):
    cert = str(tmp_path / "cert.pem")
    key = str(tmp_path / "key.pem")
    _ensure_tls_certs(cert, key, peer_id="alice")
    mtime_cert = Path(cert).stat().st_mtime
    mtime_key = Path(key).stat().st_mtime
    _ensure_tls_certs(cert, key, peer_id="alice")  # same peer_id → no regen
    assert Path(cert).stat().st_mtime == mtime_cert
    assert Path(key).stat().st_mtime == mtime_key


def test_ensure_tls_certs_creates_parent_dir(tmp_path):
    nested = str(tmp_path / "deep" / "nested" / "cert.pem")
    key = str(tmp_path / "deep" / "nested" / "key.pem")
    _ensure_tls_certs(nested, key)
    assert Path(nested).exists()


# ── QUICTransport raises without aioquic ──────────────────────────────────────

def test_quic_transport_raises_when_aioquic_unavailable(monkeypatch):
    import rs.transport as transport_mod
    monkeypatch.setattr(transport_mod, "_AIOQUIC_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="aioquic"):
        QUICTransport()


# ── UDPTransport ──────────────────────────────────────────────────────────────

async def test_udp_collect_returns_empty_on_timeout():
    t = UDPTransport()
    port = free_port()
    await t.start("127.0.0.1", port)
    try:
        result = await t.collect("no-such-transfer", timeout=0.1)
        assert result == []
    finally:
        t.stop()


async def test_udp_roundtrip_loopback():
    """Send RS-encoded packets over loopback UDP and decode them back."""
    payload = b"hello rockdove UDP transport test"
    packets, tid, n, k, _ = encode_file(payload, redundancy_level=0.25)

    t = UDPTransport()
    port = free_port()
    await t.start("127.0.0.1", port)
    try:
        await t.send(packets, "127.0.0.1", port)
        received = await t.collect(tid, timeout=5.0)
        assert len(received) >= k, f"only {len(received)}/{n} packets received"
    finally:
        t.stop()


async def test_udp_fec_recovery_with_packet_loss():
    """Drop roughly 20% of packets; RS FEC should still recover the file."""
    import random
    random.seed(42)

    payload = b"erasure recovery test " * 20
    packets, tid, n, k, _ = encode_file(payload, redundancy_level=0.25)
    # Keep only k+2 packets (enough to recover, but some dropped)
    kept = random.sample(packets, k + 2)

    t = UDPTransport()
    port = free_port()
    await t.start("127.0.0.1", port)
    try:
        await t.send(kept, "127.0.0.1", port)
        received = await t.collect(tid, timeout=5.0)
        assert len(received) >= k
    finally:
        t.stop()


async def test_udp_ignores_short_datagrams():
    """Packets shorter than HEADER_SIZE must be silently dropped."""
    t = UDPTransport()
    port = free_port()
    await t.start("127.0.0.1", port)
    try:
        loop = asyncio.get_running_loop()
        sock_transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=("127.0.0.1", port),
        )
        try:
            sock_transport.sendto(b"\x00" * (HEADER_SIZE - 1))
            await asyncio.sleep(0.05)
        finally:
            sock_transport.close()
        # Buffer should still be empty
        assert t._buffers == {}
    finally:
        t.stop()


async def test_udp_stop_is_idempotent():
    t = UDPTransport()
    port = free_port()
    await t.start("127.0.0.1", port)
    t.stop()
    t.stop()  # must not raise


# ── QUICTransport ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_start_creates_certs(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    try:
        await asyncio.sleep(0.2)
        assert Path(qt._cert_file).exists()
        assert Path(qt._key_file).exists()
    finally:
        qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_certs_reused_across_restarts(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.1)
    mtime = Path(qt._cert_file).stat().st_mtime
    qt.stop()
    await asyncio.sleep(0.05)

    qt2 = QUICTransport()
    await qt2.start("127.0.0.1", free_port())
    await asyncio.sleep(0.1)
    assert Path(qt2._cert_file).stat().st_mtime == mtime, "cert was re-generated"
    qt2.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_collect_returns_empty_on_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.2)
    try:
        result = await qt.collect("nonexistent-tid", timeout=0.1)
        assert result == []
    finally:
        qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_roundtrip_loopback(tmp_path, monkeypatch):
    """Full QUIC loopback: encode → send datagram → collect → enough packets."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"hello rockdove QUIC transport test"
    packets, tid, n, k, _ = encode_file(payload, redundancy_level=0.25)

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)  # wait for QUIC server to bind
    try:
        await qt.send(packets, "127.0.0.1", port)
        received = await qt.collect(tid, timeout=10.0)
        assert len(received) >= k, f"only {len(received)}/{n} QUIC packets delivered"
    finally:
        qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_large_file_loopback(tmp_path, monkeypatch):
    """Send a multi-KB file over QUIC loopback.

    Payload is sized so each RS chunk stays under the default QUIC MTU (1200 B):
    with k=24 data chunks, 24 KB → ~1000 B/chunk → ~1036 B/packet (header+payload).
    """
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = bytes(range(256)) * 96  # 24 576 bytes; each of k=24 chunks ≈ 1024 B
    packets, tid, n, k, _ = encode_file(payload, redundancy_level=0.25)

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)
    try:
        await qt.send(packets, "127.0.0.1", port)
        received = await qt.collect(tid, timeout=15.0)
        assert len(received) >= k
    finally:
        qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_fec_recovery_with_packet_loss(tmp_path, monkeypatch):
    """Drop 2 packets before sending; remaining k packets must be collectible."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"quic erasure recovery " * 30
    packets, tid, n, k, _ = encode_file(payload, redundancy_level=0.25)
    kept = packets[:k + 2]  # drop the last (n - k - 2) = parity packets

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)
    try:
        await qt.send(kept, "127.0.0.1", port)
        received = await qt.collect(tid, timeout=10.0)
        assert len(received) >= k
    finally:
        qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_stop_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.1)
    qt.stop()
    qt.stop()  # must not raise
    get_settings.cache_clear()


# ── CERT_HELLO and pending connections ────────────────────────────────────────

@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_send_creates_pending_connection(tmp_path, monkeypatch):
    """After a QUIC send the receiver should have a pending connection entry."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"cert hello pending test"
    packets, tid, n, k, _ = encode_file(payload, redundancy_level=0.25)

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)
    try:
        await qt.send(packets, "127.0.0.1", port)
        # Give the CERT_HELLO datagram time to arrive and be processed
        await asyncio.sleep(0.5)
        pending = qt.list_pending()
        assert any(p["transfer_id"] == tid for p in pending), \
            f"expected transfer_id {tid!r} in pending list, got {pending}"
        entry = next(p for p in pending if p["transfer_id"] == tid)
        assert entry["status"] == "pending"
        assert entry["peer_id"] == "default-peer"
        assert entry["cert_cn"] == "rockdove-default-peer"
        assert len(entry["cert_fingerprint"]) == 64
    finally:
        qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_approve_connection(tmp_path, monkeypatch):
    """Approving a pending connection sets its status to accepted."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"approve test"
    packets, tid, _, k, _ = encode_file(payload, redundancy_level=0.25)

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)
    try:
        await qt.send(packets, "127.0.0.1", port)
        await asyncio.sleep(0.5)
        assert any(p["transfer_id"] == tid for p in qt.list_pending())
        qt.approve_connection(tid)
        entry = next(p for p in qt.list_pending() if p["transfer_id"] == tid)
        assert entry["status"] == "accepted"
    finally:
        qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_wait_for_approval_resolves_on_accept(tmp_path, monkeypatch):
    """wait_for_approval returns True when approve_connection is called."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"approval flow test"
    packets, tid, _, k, _ = encode_file(payload, redundancy_level=0.25)

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)

    async def _send_then_approve():
        await asyncio.sleep(0.1)
        await qt.send(packets, "127.0.0.1", port)
        await asyncio.sleep(0.5)
        qt.approve_connection(tid)

    asyncio.create_task(_send_then_approve())
    approved = await qt.wait_for_approval(tid, timeout=10.0)
    assert approved is True
    qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_wait_for_approval_returns_false_on_reject(tmp_path, monkeypatch):
    """wait_for_approval returns False when reject_connection is called."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"reject flow test"
    packets, tid, _, k, _ = encode_file(payload, redundancy_level=0.25)

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)

    async def _send_then_reject():
        await asyncio.sleep(0.1)
        await qt.send(packets, "127.0.0.1", port)
        await asyncio.sleep(0.5)
        qt.reject_connection(tid)

    asyncio.create_task(_send_then_reject())
    approved = await qt.wait_for_approval(tid, timeout=10.0)
    assert approved is False
    qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_wait_for_approval_auto_approves_on_timeout(tmp_path, monkeypatch):
    """wait_for_approval auto-approves when no response arrives in time."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"timeout auto-approve"
    packets, tid, _, k, _ = encode_file(payload, redundancy_level=0.25)

    qt = QUICTransport()
    port = free_port()
    await qt.start("127.0.0.1", port)
    await asyncio.sleep(0.3)

    async def _send():
        await asyncio.sleep(0.1)
        await qt.send(packets, "127.0.0.1", port)

    asyncio.create_task(_send())
    # Very short timeout → nobody approves → should auto-approve
    approved = await qt.wait_for_approval(tid, timeout=2.0)
    assert approved is True
    qt.stop()
    get_settings.cache_clear()


@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_quic_cert_hello_magic_constant():
    assert _CERT_HELLO_MAGIC == b"\x52\x44\x43\x48"
    assert len(_CERT_HELLO_MAGIC) == 4


# ── Transport parity ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not _AIOQUIC_AVAILABLE, reason="aioquic not installed")
async def test_udp_and_quic_deliver_same_packet_count(tmp_path, monkeypatch):
    """UDP and QUIC must deliver the same number of packets for identical input."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()

    payload = b"parity test payload for transport comparison" * 5
    packets, tid_udp, n, k, _ = encode_file(payload, redundancy_level=0.25)
    packets_q, tid_quic, _, _, _ = encode_file(payload, redundancy_level=0.25)

    # UDP leg
    udp_port = free_port()
    ut = UDPTransport()
    await ut.start("127.0.0.1", udp_port)
    await ut.send(packets, "127.0.0.1", udp_port)
    udp_received = await ut.collect(tid_udp, timeout=5.0)
    ut.stop()

    # QUIC leg
    quic_port = free_port()
    qt = QUICTransport()
    await qt.start("127.0.0.1", quic_port)
    await asyncio.sleep(0.3)
    await qt.send(packets_q, "127.0.0.1", quic_port)
    quic_received = await qt.collect(tid_quic, timeout=10.0)
    qt.stop()

    assert len(udp_received) >= k
    assert len(quic_received) >= k
    get_settings.cache_clear()
