from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def fetch_prices_history(
    *,
    host: str,
    token_id: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
    fidelity: int = 1,
    interval: str | None = None,
    timeout_sec: float = 60.0,
) -> list[dict[str, Any]]:
    """GET ``/prices-history`` for one CLOB token (public, no auth).

    Returns raw history rows ``[{"t": int, "p": float}, ...]`` (may be empty).
    """
    base = host.rstrip("/")
    q: dict[str, str] = {"market": token_id, "fidelity": str(int(fidelity))}
    if start_ts is not None:
        q["startTs"] = str(int(start_ts))
    if end_ts is not None:
        q["endTs"] = str(int(end_ts))
    if interval:
        q["interval"] = interval
    url = f"{base}/prices-history?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"prices-history HTTP {exc.code} for {token_id!r}: {exc.read()!r}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"prices-history network error for {token_id!r}: {exc}") from exc

    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"prices-history: expected object, got {type(data).__name__}")
    hist = data.get("history")
    if hist is None:
        return []
    if not isinstance(hist, list):
        raise ValueError("prices-history: 'history' must be a list")
    out: list[dict[str, Any]] = []
    for row in hist:
        if not isinstance(row, dict):
            continue
        out.append(row)
    return out


def history_to_points(history: list[dict[str, Any]]) -> list[tuple[int, float]]:
    """Normalize API rows to sorted ``(t, p)`` with basic validation."""
    pts: list[tuple[int, float]] = []
    for row in history:
        if "t" not in row or "p" not in row:
            continue
        try:
            t_i = int(row["t"])
            p_f = float(row["p"])
        except (TypeError, ValueError):
            continue
        pts.append((t_i, p_f))
    pts.sort(key=lambda x: x[0])
    return pts


def sleep_backoff(attempt: int, *, base: float = 1.0, cap: float = 60.0) -> None:
    delay = min(cap, base * (2**max(0, attempt)))
    time.sleep(delay)
