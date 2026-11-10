"""Userspace UDP impairment proxy (delay/jitter/loss/rate); no root or tc/netem needed."""
import argparse
import asyncio
import json
import random
import socket
import time
from urllib.parse import parse_qs, urlparse


class Impair(asyncio.DatagramProtocol):
    def __init__(self, target, delay_ms, jitter_ms, loss_pct, rate_bps):
        self.target, self.delay_ms, self.jitter_ms = target, delay_ms, jitter_ms
        self.loss_pct, self.rate_bps = loss_pct, rate_bps
        self.transport = None
        self._tokens, self._last = rate_bps, time.monotonic()
        self.reset()

    def reset(self):
        self.stats = {"received": 0, "dropped": 0, "forwarded": 0, "bytes": 0}

    def connection_made(self, transport):
        self.transport = transport

    def _wait_for_tokens(self, size):
        if self.rate_bps <= 0:
            return 0.0
        now = time.monotonic()
        self._tokens = min(self.rate_bps, self._tokens + (now - self._last) * self.rate_bps)
        self._last = now
        if self._tokens >= size:
            self._tokens -= size
            return 0.0
        deficit, self._tokens = size - self._tokens, 0.0
        return deficit / self.rate_bps

    def datagram_received(self, data, addr):
        self.stats["received"] += 1
        if random.random() * 100 < self.loss_pct:
            self.stats["dropped"] += 1
            return
        delay = max(0.0, (self.delay_ms + random.uniform(-self.jitter_ms, self.jitter_ms)) / 1000)
        asyncio.get_running_loop().call_later(delay + self._wait_for_tokens(len(data)), self._forward, data)

    def _forward(self, data):
        self.transport.sendto(data, self.target)
        self.stats["forwarded"] += 1
        self.stats["bytes"] += len(data)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen-host", default="0.0.0.0")
    ap.add_argument("--listen-port", type=int, required=True)
    ap.add_argument("--target-host", required=True)
    ap.add_argument("--target-port", type=int, required=True)
    ap.add_argument("--control-port", type=int, default=9300)
    ap.add_argument("--delay-ms", type=float, default=0)
    ap.add_argument("--jitter-ms", type=float, default=0)
    ap.add_argument("--loss-pct", type=float, default=0)
    ap.add_argument("--rate-bps", type=float, default=0, help="bytes/s, 0 = unlimited")
    a = ap.parse_args()

    loop = asyncio.get_running_loop()
    proto = Impair((a.target_host, a.target_port), a.delay_ms, a.jitter_ms, a.loss_pct, a.rate_bps)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)  # agents send bursts
    sock.bind((a.listen_host, a.listen_port))
    transport, _ = await loop.create_datagram_endpoint(lambda: proto, sock=sock)

    async def control(reader, writer):
        line = (await reader.readline()).decode(errors="replace")
        while (await reader.readline()).strip():
            pass
        url = urlparse(line.split(" ")[1] if " " in line else "/")
        q = {k: float(v[0]) for k, v in parse_qs(url.query).items()}
        if url.path == "/set":
            proto.loss_pct = q.get("loss", proto.loss_pct)
            proto.delay_ms = q.get("delay", proto.delay_ms)
            proto.jitter_ms = q.get("jitter", proto.jitter_ms)
            proto.rate_bps = q.get("rate", proto.rate_bps)
        if url.path in ("/set", "/reset"):
            proto.reset()
        body = json.dumps({**proto.stats, "loss": proto.loss_pct, "delay_ms": proto.delay_ms,
                           "jitter_ms": proto.jitter_ms, "rate_bps": proto.rate_bps})
        writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}".encode())
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(control, a.listen_host, a.control_port)
    try:
        await asyncio.Event().wait()
    finally:
        transport.close()
        server.close()


if __name__ == "__main__":
    asyncio.run(main())
