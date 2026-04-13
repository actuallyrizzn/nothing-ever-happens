from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def token_ingest_params_hash(
    *,
    token_id: str,
    start_ts: int | None,
    end_ts: int | None,
    fidelity: int,
    interval: str | None,
) -> str:
    payload = {
        "token_id": token_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "fidelity": int(fidelity),
        "interval": interval,
    }
    return canonical_json_hash(payload)
