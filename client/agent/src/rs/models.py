from dataclasses import dataclass
from enum import Enum


class TransferStatus(str, Enum):
    ok = "ok"
    degraded = "degraded"
    failed = "failed"
    pending = "pending"
    relayed = "relayed"


@dataclass
class DecodeResult:
    transfer_id: str
    status: TransferStatus
    file_bytes: bytes | None = None
    recovered_blocks: int = 0
    total_blocks: int = 0
    reason: str | None = None
