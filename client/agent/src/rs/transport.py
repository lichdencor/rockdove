"""
Transport layer abstraction for RS block delivery.

Two implementations:
  UDPTransport  — raw asyncio UDP sockets, no TLS.  Default (TRANSPORT_MODE=udp).
  QUICTransport — aioquic over the same UDP port, TLS 1.3 native via QUIC
                  DATAGRAM extension (RFC 9221).  Enabled with TRANSPORT_MODE=quic.

Both share UDP_PORT.  They are mutually exclusive — the agent runs one at a time.
The active transport is announced in peer registration so remote senders know
which client protocol to use.

QUIC peer identity:
  Each peer generates a self-signed RSA-2048 TLS cert whose CN is
  "rockdove-{peer_id}".  Before sending RS blocks the sender emits a
  CERT_HELLO datagram containing its peer_id, the transfer_id, and the
  SHA-256 fingerprint of its cert.  The receiver surfaces this as a
  pending incoming connection that the operator can approve or reject
  via the REST API / UI before the decoded file is committed to storage.

Invariant (from RULES.md): only this module opens UDP/QUIC sockets.
"""
from __future__ import annotations

import asyncio
import hashlib
import ssl
import struct
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from .encoder import HEADER_FMT, HEADER_SIZE

# Magic header that identifies a CERT_HELLO datagram (RDCH = RockDove Connection Hello)
_CERT_HELLO_MAGIC = b"\x52\x44\x43\x48"

# ── Shared receive buffer ──────────────────────────────────────────────────────

class _TransferBuffer:
    def __init__(self, total: int):
        self.total = total
        self.packets: dict[int, bytes] = {}
        self._done = asyncio.Event()

    def add(self, index: int, raw: bytes) -> None:
        self.packets[index] = raw
        if len(self.packets) >= self.total:
            self._done.set()

    async def wait(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass


# ── Abstract interface ─────────────────────────────────────────────────────────

class BaseTransport(ABC):
    @abstractmethod
    async def start(self, host: str, port: int) -> None:
        """Bind the listener socket on the given host:port."""

    @abstractmethod
    async def send(self, packets: list[bytes], host: str, port: int) -> None:
        """Deliver a list of RS block packets to a remote peer."""

    @abstractmethod
    async def collect(self, transfer_id: str, timeout: float = 30.0) -> list[bytes]:
        """Wait for all packets of a transfer and return them in arrival order."""

    @abstractmethod
    def stop(self) -> None:
        """Close and release the listener socket."""


# ── UDP implementation ─────────────────────────────────────────────────────────

class _UDPListenerProtocol(asyncio.DatagramProtocol):
    def __init__(self, buffers: dict[str, _TransferBuffer]):
        self._buffers = buffers

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) <= HEADER_SIZE:
            return
        hdr = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
        tid = hdr[0].hex()
        block_index = hdr[1]
        total_blocks = hdr[2]
        if tid not in self._buffers:
            self._buffers[tid] = _TransferBuffer(total_blocks)
        self._buffers[tid].add(block_index, data)

    def error_received(self, exc: Exception) -> None:
        pass


class UDPTransport(BaseTransport):
    def __init__(self) -> None:
        self._buffers: dict[str, _TransferBuffer] = {}
        self._listener: asyncio.BaseTransport | None = None

    async def start(self, host: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        self._listener, _ = await loop.create_datagram_endpoint(
            lambda: _UDPListenerProtocol(self._buffers),
            local_addr=(host, port),
        )

    async def send(self, packets: list[bytes], host: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=(host, port),
        )
        try:
            for pkt in packets:
                transport.sendto(pkt)
                await asyncio.sleep(0)
        finally:
            transport.close()

    async def collect(self, transfer_id: str, timeout: float = 30.0) -> list[bytes]:
        deadline = time.monotonic() + timeout
        while transfer_id not in self._buffers:
            if time.monotonic() > deadline:
                return []
            await asyncio.sleep(0.05)
        remaining = deadline - time.monotonic()
        await self._buffers[transfer_id].wait(timeout=max(0.0, remaining))
        buf = self._buffers.pop(transfer_id, None)
        return list(buf.packets.values()) if buf else []

    def stop(self) -> None:
        if self._listener:
            self._listener.close()


# ── TLS cert helpers ───────────────────────────────────────────────────────────

def _cert_cn_matches(cert_file: str, expected_cn: str) -> bool:
    """Return True if the cert at cert_file has CN == expected_cn."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        cert = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
        cns = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return bool(cns) and cns[0].value == expected_cn
    except Exception:
        return False


def _ensure_tls_certs(cert_file: str, key_file: str, peer_id: str = "peer") -> None:
    """
    Generate a self-signed TLS cert+key for this peer if they don't exist or
    the CN no longer matches (e.g. PEER_ID env changed).
    CN = "rockdove-{peer_id}"
    """
    cn = f"rockdove-{peer_id}"
    if Path(cert_file).exists() and Path(key_file).exists():
        if _cert_cn_matches(cert_file, cn):
            return
        # CN mismatch — peer_id changed; regenerate.
        Path(cert_file).unlink(missing_ok=True)
        Path(key_file).unlink(missing_ok=True)

    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    Path(cert_file).parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_file, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )


# ── QUIC implementation ────────────────────────────────────────────────────────

_AIOQUIC_AVAILABLE = False

try:
    from aioquic.asyncio import connect as _quic_connect
    from aioquic.asyncio import serve as _quic_serve
    from aioquic.asyncio.protocol import QuicConnectionProtocol
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import DatagramFrameReceived, QuicEvent

    class _QUICServerProtocol(QuicConnectionProtocol):
        def __init__(self, *args, buffers: dict, on_connect=None, **kwargs):
            super().__init__(*args, **kwargs)
            self._buffers = buffers
            self._on_connect = on_connect

        def _handle_cert_hello(self, data: bytes) -> None:
            """Parse a CERT_HELLO datagram and fire the on_connect callback."""
            try:
                offset = 4  # skip RDCH magic
                version = data[offset]; offset += 1
                if version != 0x01:
                    return
                pid_len = data[offset]; offset += 1
                peer_id = data[offset:offset + pid_len].decode("utf-8"); offset += pid_len
                tid_bytes = data[offset:offset + 16]; offset += 16
                fingerprint = data[offset:offset + 64].decode("ascii")
                if self._on_connect:
                    self._on_connect(peer_id, tid_bytes.hex(), fingerprint)
            except Exception:
                pass

        def quic_event_received(self, event: QuicEvent) -> None:
            if not isinstance(event, DatagramFrameReceived):
                return
            data = event.data
            if data[:4] == _CERT_HELLO_MAGIC:
                self._handle_cert_hello(data)
                return
            if len(data) <= HEADER_SIZE:
                return
            hdr = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
            tid = hdr[0].hex()
            block_index = hdr[1]
            total_blocks = hdr[2]
            if tid not in self._buffers:
                self._buffers[tid] = _TransferBuffer(total_blocks)
            self._buffers[tid].add(block_index, data)

    class _QUICClientProtocol(QuicConnectionProtocol):
        def quic_event_received(self, event: QuicEvent) -> None:
            pass

        async def send_cert_hello(self, hello: bytes) -> None:
            """Send the CERT_HELLO datagram and flush before RS packets follow."""
            self._quic.send_datagram_frame(hello)
            self.transmit()
            await asyncio.sleep(0.05)

        async def send_packets(self, packets: list[bytes]) -> None:
            for pkt in packets:
                self._quic.send_datagram_frame(pkt)
                await asyncio.sleep(0)
            self.transmit()
            await asyncio.sleep(0.05)

    async def _run_quic_server(
        host: str,
        port: int,
        config: "QuicConfiguration",
        create_protocol,
    ) -> None:
        # serve() returns a QuicServer object (not a context manager in aioquic 1.x)
        server = await _quic_serve(
            host, port, configuration=config, create_protocol=create_protocol
        )
        try:
            await asyncio.Future()  # run until cancelled
        finally:
            server.close()

    _AIOQUIC_AVAILABLE = True

except ImportError:
    pass


class QUICTransport(BaseTransport):
    """QUIC transport (aioquic + RFC 9221 DATAGRAM extension).

    RS blocks are sent as QUIC datagrams — intentionally unreliable so the
    Reed-Solomon FEC can demonstrate erasure recovery, while TLS 1.3 encryption
    is provided transparently by the QUIC handshake.

    Peer identity:
      The sender emits a CERT_HELLO datagram before the RS blocks.  The
      receiver stores it as a pending incoming connection and exposes it
      via list_pending() / approve_connection() / reject_connection().
      _process_incoming() in the transfers router waits for approval
      (auto-approves on timeout so the transfer doesn't stall).
    """

    def __init__(self) -> None:
        if not _AIOQUIC_AVAILABLE:
            raise RuntimeError(
                "aioquic is not installed. "
                "Run: uv add aioquic  (inside client/agent/)"
            )
        self._buffers: dict[str, _TransferBuffer] = {}
        self._cert_file: str = ""
        self._key_file: str = ""
        self._server_task: asyncio.Task | None = None
        # Incoming connection tracking (receiver side)
        self._pending_conns: dict[str, dict] = {}
        self._approval_events: dict[str, asyncio.Event] = {}
        self._rejection_events: dict[str, asyncio.Event] = {}

    # ── cert lifecycle ─────────────────────────────────────────────────────────

    def _init_cert_paths(self) -> None:
        """Lazily set up cert paths and generate cert if needed."""
        if self._cert_file and self._key_file:
            return
        from config import get_settings
        s = get_settings()
        storage = Path(s.STORAGE_PATH)
        storage.mkdir(parents=True, exist_ok=True)
        self._cert_file = str(storage / "quic_cert.pem")
        self._key_file = str(storage / "quic_key.pem")
        _ensure_tls_certs(self._cert_file, self._key_file, s.PEER_ID)

    # ── BaseTransport interface ────────────────────────────────────────────────

    async def start(self, host: str, port: int) -> None:
        self._init_cert_paths()

        config = QuicConfiguration(is_client=False, max_datagram_frame_size=65536)
        config.load_cert_chain(self._cert_file, self._key_file)

        buffers = self._buffers
        on_connect = self._on_quic_connect

        def make_protocol(*args, **kwargs):
            return _QUICServerProtocol(
                *args, buffers=buffers, on_connect=on_connect, **kwargs
            )

        self._server_task = asyncio.create_task(
            _run_quic_server(host, port, config, make_protocol)
        )

    async def send(self, packets: list[bytes], host: str, port: int) -> None:
        self._init_cert_paths()

        from config import get_settings
        peer_id = get_settings().PEER_ID
        cert_pem_bytes = Path(self._cert_file).read_bytes()
        fingerprint = hashlib.sha256(cert_pem_bytes).hexdigest()  # 64 hex chars

        pid_bytes = peer_id.encode("utf-8")
        tid_bytes = packets[0][:16]  # first 16 bytes of any RS packet = transfer_id

        hello = (
            _CERT_HELLO_MAGIC
            + bytes([0x01])               # version
            + bytes([len(pid_bytes)])      # peer_id length
            + pid_bytes                   # peer_id UTF-8
            + tid_bytes                   # transfer_id (16 raw bytes)
            + fingerprint.encode("ascii") # 64 ASCII hex chars
        )

        config = QuicConfiguration(is_client=True, max_datagram_frame_size=65536)
        config.verify_mode = ssl.CERT_NONE

        async with _quic_connect(
            host,
            port,
            configuration=config,
            create_protocol=_QUICClientProtocol,
            wait_connected=True,
        ) as proto:
            await proto.send_cert_hello(hello)
            await proto.send_packets(packets)

    async def collect(self, transfer_id: str, timeout: float = 30.0) -> list[bytes]:
        deadline = time.monotonic() + timeout
        while transfer_id not in self._buffers:
            if time.monotonic() > deadline:
                return []
            await asyncio.sleep(0.05)
        remaining = deadline - time.monotonic()
        await self._buffers[transfer_id].wait(timeout=max(0.0, remaining))
        buf = self._buffers.pop(transfer_id, None)
        # Clean up pending connection metadata once the buffer is consumed.
        self._pending_conns.pop(transfer_id, None)
        self._approval_events.pop(transfer_id, None)
        self._rejection_events.pop(transfer_id, None)
        return list(buf.packets.values()) if buf else []

    def stop(self) -> None:
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()

    # ── Incoming connection API (receiver side) ────────────────────────────────

    def _on_quic_connect(self, peer_id: str, transfer_id: str, fingerprint: str) -> None:
        """Called by _QUICServerProtocol when a CERT_HELLO datagram arrives."""
        self._pending_conns[transfer_id] = {
            "transfer_id": transfer_id,
            "peer_id": peer_id,
            "cert_cn": f"rockdove-{peer_id}",
            "cert_fingerprint": fingerprint,
            "arrived_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        self._approval_events[transfer_id] = asyncio.Event()
        self._rejection_events[transfer_id] = asyncio.Event()

    async def wait_for_approval(self, transfer_id: str, timeout: float = 30.0) -> bool:
        """
        Wait for the operator to accept or reject this incoming QUIC connection.

        Returns True  → proceed with decoding (approved or no CERT_HELLO received).
        Returns False → caller should discard buffers (explicitly rejected).

        Auto-approves on timeout so the transfer never stalls indefinitely.
        """
        deadline = time.monotonic() + timeout

        # Wait up to 5 s for the CERT_HELLO datagram to arrive.
        hello_deadline = time.monotonic() + min(5.0, timeout)
        while transfer_id not in self._pending_conns:
            if time.monotonic() > hello_deadline:
                return True  # no CERT_HELLO → not a cert-aware sender; allow through
            await asyncio.sleep(0.1)

        approve_event = self._approval_events.get(transfer_id)
        reject_event = self._rejection_events.get(transfer_id)
        if not approve_event or not reject_event:
            return True

        remaining = max(0.0, deadline - time.monotonic())
        approve_task = asyncio.create_task(approve_event.wait())
        reject_task = asyncio.create_task(reject_event.wait())
        done, pending_tasks = await asyncio.wait(
            {approve_task, reject_task},
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending_tasks:
            t.cancel()

        if not done:
            return True  # timeout → auto-approve

        return not reject_event.is_set()

    def approve_connection(self, transfer_id: str) -> None:
        self._pending_conns[transfer_id]["status"] = "accepted"
        ev = self._approval_events.get(transfer_id)
        if ev:
            ev.set()

    def reject_connection(self, transfer_id: str) -> None:
        self._pending_conns[transfer_id]["status"] = "rejected"
        ev = self._rejection_events.get(transfer_id)
        if ev:
            ev.set()

    def list_pending(self) -> list[dict]:
        return list(self._pending_conns.values())

    def clear_buffer(self, transfer_id: str) -> None:
        """Discard all buffered packets and pending metadata for a transfer."""
        self._buffers.pop(transfer_id, None)
        self._pending_conns.pop(transfer_id, None)
        self._approval_events.pop(transfer_id, None)
        self._rejection_events.pop(transfer_id, None)


# ── Module-level singleton ─────────────────────────────────────────────────────
# Initialised as UDP; main.py lifespan replaces it via set_transport() before
# any transfers happen.

_transport: BaseTransport = UDPTransport()


def get_transport() -> BaseTransport:
    return _transport


def set_transport(t: BaseTransport) -> None:
    global _transport
    _transport = t
