"""End-to-end smoke: upload on rd-a, send to rd-b, verify the bytes arrive. Stdlib only."""
import hashlib
import json
import os
import sys
import urllib.request
import uuid

A = os.environ.get("AGENT_A_URL", "http://localhost:18001")
B = os.environ.get("AGENT_B_URL", "http://localhost:18002")
SIZE = int(os.environ.get("SMOKE_SIZE", 200_000))


def call(method, url, body=None, headers=None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main() -> int:
    data = os.urandom(SIZE)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"smoke.bin\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    meta = json.loads(call("POST", f"{A}/files/", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    res = json.loads(call("POST", f"{A}/transfer/send",
                          json.dumps({"file_id": meta["file_id"], "target_peer_id": "rd-b"}).encode(),
                          {"Content-Type": "application/json"}))
    print(json.dumps(res))
    digest = hashlib.sha256(data).hexdigest()
    received = any(f["sha256"] == digest for f in json.loads(call("GET", f"{B}/files/")))
    ok = res.get("status") != "failed" and received
    print("SHA256", digest, "received_by_rd-b:", received, "->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
