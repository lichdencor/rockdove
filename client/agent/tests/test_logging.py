import json
import logging

from logging_setup import JsonFormatter


def test_json_formatter_includes_ts_and_extras():
    record = logging.LogRecord("access", logging.INFO, __file__, 1, "http_request", None, None)
    record.user = "alice"
    record.client_ip = "10.0.0.1"
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "http_request"
    assert out["user"] == "alice" and out["client_ip"] == "10.0.0.1"
    assert out["ts"].endswith("+00:00")
