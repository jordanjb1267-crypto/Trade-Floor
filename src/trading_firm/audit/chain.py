"""Hash-chained append-only audit log (§8.1 Audit Service, §17, N-5).

Each JSONL record embeds the previous record's hash; verify() walks the
chain and reports the first broken link. Off-machine anchoring (pushing the
latest hash to the private repo) happens in operational tooling.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

GENESIS = "0" * 64


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _record_hash(seq: int, ts: str, event_type: str, payload: dict, prev_hash: str) -> str:
    material = f"{seq}|{ts}|{event_type}|{_canonical(payload)}|{prev_hash}"
    return hashlib.sha256(material.encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _last(self) -> tuple[int, str]:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return 0, GENESIS
        last_line = self._path.read_text().rstrip("\n").rsplit("\n", 1)[-1]
        record = json.loads(last_line)
        return record["seq"], record["hash"]

    def append(self, event_type: str, payload: dict) -> dict:
        """Append one record. Timestamps are aware UTC (§10.3)."""
        seq, prev_hash = self._last()
        seq += 1
        ts = dt.datetime.now(dt.UTC).isoformat()
        record = {
            "seq": seq,
            "ts": ts,
            "type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
            "hash": _record_hash(seq, ts, event_type, payload, prev_hash),
        }
        with self._path.open("a") as fh:
            fh.write(_canonical(record) + "\n")
        return record

    def verify(self) -> tuple[bool, int | None]:
        """Walk the chain. Returns (ok, first_bad_seq)."""
        if not self._path.exists():
            return True, None
        prev_hash = GENESIS
        expected_seq = 0
        for line in self._path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            expected_seq += 1
            recomputed = _record_hash(
                record["seq"], record["ts"], record["type"], record["payload"], record["prev_hash"]
            )
            if (
                record["seq"] != expected_seq
                or record["prev_hash"] != prev_hash
                or record["hash"] != recomputed
            ):
                return False, expected_seq
            prev_hash = record["hash"]
        return True, None

    def head_hash(self) -> str:
        """Latest chain hash — the value to anchor off-machine (N-5)."""
        return self._last()[1]
