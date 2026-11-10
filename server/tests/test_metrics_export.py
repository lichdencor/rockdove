import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi.testclient import TestClient

from metrics.models import MetricReport


class FakeRedis:
    def __init__(self, data):
        self.data = data

    async def scan_iter(self, pattern):
        for k in self.data:
            yield k

    async def lrange(self, key, a, b):
        return self.data.get(key, [])


def _client(monkeypatch, data):
    import main
    import metrics.router as mr
    monkeypatch.setattr(mr, "get_redis", lambda: FakeRedis(data))
    return TestClient(main.app)


def _raw(peer, rtt):
    return MetricReport(peer_id=peer, rtt_ms=rtt, jitter_ms=1, loss_rate=0.1).model_dump_json()


def test_export_json_and_csv(monkeypatch):
    c = _client(monkeypatch, {"metrics:a": [_raw("a", 20), _raw("a", 10)], "metrics:b": [_raw("b", 5)]})
    samples = c.get("/metrics/export").json()["samples"]
    assert [s["rtt_ms"] for s in samples] == [10, 20, 5]
    csv_text = c.get("/metrics/export?format=csv&peer_id=b").text
    assert csv_text.splitlines()[0].startswith("peer_id,target_peer_id,rtt_ms")
    assert len(csv_text.strip().splitlines()) == 2
