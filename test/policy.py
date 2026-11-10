"""Incoming access-list matrix: rd-a -> rd-b under each policy on rd-b. Stdlib only."""
import json
import os
import sys
import urllib.error
import urllib.request

A = os.environ.get("AGENT_A_URL", "http://localhost:18001")
B = os.environ.get("AGENT_B_URL", "http://localhost:18002")

CASES = [
    ({"incoming_policy": "allow_all"}, True),
    ({"incoming_policy": "deny_all"}, False),
    ({"incoming_policy": "allow_list", "incoming_allowed_peers": "rd-x"}, False),
    ({"incoming_policy": "allow_list", "incoming_allowed_peers": "rd-a"}, True),
    ({"incoming_policy": "deny_list", "incoming_denied_peers": "rd-a"}, False),
    ({"incoming_policy": "deny_list", "incoming_denied_peers": "rd-z"}, True),
]


def call(method, url, body=None, headers=None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def delivered() -> bool:
    boundary = "b" + os.urandom(8).hex()
    data = os.urandom(50_000)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"p.bin\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    meta = json.loads(call("POST", f"{A}/files/", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    try:
        res = json.loads(call("POST", f"{A}/transfer/send",
                              json.dumps({"file_id": meta["file_id"], "target_peer_id": "rd-b"}).encode(),
                              {"Content-Type": "application/json"}))
    except urllib.error.HTTPError:
        return False
    return res.get("status") != "failed"


def main() -> int:
    failed = 0
    for cfg, expected in CASES:
        call("PUT", f"{B}/config", json.dumps({"incoming_denied_peers": "", "incoming_allowed_peers": "", **cfg}).encode(),
             {"Content-Type": "application/json"})
        got = delivered()
        ok = got == expected
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} {cfg} expected_delivered={expected} got={got}")
    call("PUT", f"{B}/config", json.dumps({"incoming_policy": "allow_all"}).encode(), {"Content-Type": "application/json"})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
