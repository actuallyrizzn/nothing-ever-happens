from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bot.backtest.clob_prices import fetch_prices_history, history_to_points, sleep_backoff
from bot.backtest.hashing import token_ingest_params_hash
from bot.backtest.io_util import ArchiveFileLock, iter_jsonl


@dataclass
class IngestStats:
    markets_requested: int = 0
    markets_ok: int = 0
    markets_empty: int = 0
    markets_partial: int = 0
    errors: list[str] = field(default_factory=list)


class SlidingWindowLimiter:
    """Rough throttle: at most ``max_events`` starts of work per ``window_sec``."""

    def __init__(self, max_events: int, window_sec: float) -> None:
        self.max_events = max_events
        self.window_sec = window_sec
        self._ts: list[float] = []

    def acquire(self) -> None:
        now = time.monotonic()
        self._ts = [t for t in self._ts if now - t <= self.window_sec]
        if len(self._ts) >= self.max_events:
            wait = self.window_sec - (now - self._ts[0]) + 0.05
            if wait > 0:
                time.sleep(wait)
            now = time.monotonic()
            self._ts = [t for t in self._ts if now - t <= self.window_sec]
        self._ts.append(time.monotonic())


def _prices_path(archive: Path, token_id: str) -> Path:
    return archive / "prices" / f"{token_id}.parquet"


def _load_checkpoint(archive: Path) -> dict[str, Any]:
    p = archive / "ingest_checkpoint.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_checkpoint(archive: Path, data: dict[str, Any]) -> None:
    p = archive / "ingest_checkpoint.json"
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _write_prices_parquet(
    path: Path,
    *,
    token_id: str,
    points: list[tuple[int, float]],
    ingest_run_id: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(points)
    if n == 0:
        table = pa.table(
            {
                "token_id": pa.array([], type=pa.string()),
                "t": pa.array([], type=pa.int64()),
                "p": pa.array([], type=pa.float64()),
                "ingest_run_id": pa.array([], type=pa.string()),
                "source": pa.array([], type=pa.string()),
            }
        )
    else:
        ts, ps = zip(*points)
        table = pa.table(
            {
                "token_id": [token_id] * n,
                "t": list(ts),
                "p": list(ps),
                "ingest_run_id": [ingest_run_id] * n,
                "source": ["clob_prices_history"] * n,
            }
        )
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)


def _merge_points(
    existing: list[tuple[int, float]],
    new_points: list[tuple[int, float]],
) -> list[tuple[int, float]]:
    by_t: dict[int, float] = {}
    for t, p in existing + new_points:
        by_t[int(t)] = float(p)
    return sorted(by_t.items(), key=lambda x: x[0])


def _read_existing_points(path: Path, token_id: str) -> list[tuple[int, float]]:
    if not path.exists():
        return []
    table = pq.read_table(path, columns=["t", "p"])
    ts = table["t"].to_pylist()
    ps = table["p"].to_pylist()
    return [(int(t), float(p)) for t, p in zip(ts, ps)]


def run_ingest(
    *,
    archive: Path,
    universe_path: Path,
    host: str = "https://clob.polymarket.com",
    fidelity: int = 1,
    interval: str | None = None,
    max_requests_per_10s: int = 800,
    force: bool = False,
    resume: bool = True,
    max_retries: int = 4,
) -> IngestStats:
    """Ingest ``prices-history`` for each row in a JSONL universe file."""
    archive = Path(archive).resolve()
    universe_path = Path(universe_path).resolve()
    stats = IngestStats()
    ingest_run_id = str(uuid.uuid4())
    limiter = SlidingWindowLimiter(max_requests_per_10s, 10.0)

    with ArchiveFileLock(archive):
        checkpoint = _load_checkpoint(archive) if resume else {}
        completed: dict[str, str] = dict(checkpoint.get("completed") or {})

        by_token: dict[str, dict[str, Any]] = {}
        u_existing = archive / "universe.parquet"
        if u_existing.exists():
            try:
                prev = pq.read_table(u_existing)
                for r in prev.to_pylist():
                    tid = str(r.get("no_token_id") or "")
                    if tid:
                        by_token[tid] = dict(r)
            except Exception as exc:
                stats.errors.append(f"load_universe_parquet:{exc}")

        rows = list(iter_jsonl(universe_path))
        stats.markets_requested = len(rows)

        for row in rows:
            token_id = str(row.get("no_token_id") or row.get("token_id") or "").strip()
            if not token_id:
                stats.errors.append("row_missing_no_token_id")
                continue

            slug = str(row.get("slug") or token_id[:16])
            start_ts = row.get("start_ts")
            end_ts = row.get("end_ts")
            st = int(start_ts) if start_ts is not None else None
            et = int(end_ts) if end_ts is not None else None

            param_hash = token_ingest_params_hash(
                token_id=token_id,
                start_ts=st,
                end_ts=et,
                fidelity=fidelity,
                interval=interval,
            )
            if not force and completed.get(token_id) == param_hash:
                continue

            out_path = _prices_path(archive, token_id)
            existing: list[tuple[int, float]] = []
            if resume and out_path.exists() and not force:
                try:
                    existing = _read_existing_points(out_path, token_id)
                except Exception as exc:
                    stats.errors.append(f"read_existing:{token_id}:{exc}")

            history: list[dict[str, Any]] = []
            last_err: str | None = None
            for attempt in range(max_retries):
                try:
                    limiter.acquire()
                    history = fetch_prices_history(
                        host=host,
                        token_id=token_id,
                        start_ts=st,
                        end_ts=et,
                        fidelity=fidelity,
                        interval=interval,
                    )
                    last_err = None
                    break
                except (RuntimeError, ValueError, OSError) as exc:
                    last_err = str(exc)
                    sleep_backoff(attempt)

            if last_err is not None:
                stats.errors.append(f"fetch_failed:{token_id}:{last_err}")
                continue

            new_pts = history_to_points(history)
            merged = _merge_points(existing, new_pts)
            _write_prices_parquet(
                out_path,
                token_id=token_id,
                points=merged,
                ingest_run_id=ingest_run_id,
            )

            bar_count = len(merged)
            if bar_count == 0:
                coverage = "empty_history"
                stats.markets_empty += 1
            elif st is not None and et is not None and merged:
                t_min, t_max = merged[0][0], merged[-1][0]
                partial = t_min > st + 60 or t_max < et - 60
                coverage = "partial_range" if partial else "ok"
                if partial:
                    stats.markets_partial += 1
            else:
                coverage = "ok"

            t_open = row.get("t_open")
            t_open_i = int(t_open) if t_open is not None else (merged[0][0] if merged else 0)
            t_open_source = str(row.get("t_open_source") or "first_history_bar")

            outcome = row.get("outcome_no_wins")
            outcome_b: bool | None
            if outcome is None:
                outcome_b = None
            elif isinstance(outcome, bool):
                outcome_b = outcome
            else:
                outcome_b = str(outcome).lower() in {"1", "true", "yes"}

            res_status = str(row.get("resolution_status") or "unknown")

            by_token[token_id] = {
                "slug": slug,
                "no_token_id": token_id,
                "yes_token_id": row.get("yes_token_id"),
                "condition_id": str(row.get("condition_id") or ""),
                "t_open": t_open_i,
                "t_open_source": t_open_source,
                "t_end": int(row["t_end"]) if row.get("t_end") is not None else 0,
                "outcome_no_wins": outcome_b,
                "resolution_status": res_status,
                "gamma_snapshot_utc": row.get("gamma_snapshot_utc") or "",
                "ingest_version": "1",
                "coverage_class": coverage,
                "bar_count": bar_count,
                "min_order_size": float(row.get("min_order_size") or 0),
            }

            completed[token_id] = param_hash
            stats.markets_ok += 1
            _save_checkpoint(
                archive,
                {
                    "ingest_run_id": ingest_run_id,
                    "completed": completed,
                    "updated_at": time.time(),
                },
            )

        ordered: list[dict[str, Any]] = []
        for row in rows:
            tid = str(row.get("no_token_id") or row.get("token_id") or "").strip()
            if tid and tid in by_token:
                ordered.append(by_token[tid])

        if ordered:
            table = pa.Table.from_pylist(ordered)
            u_path = archive / "universe.parquet"
            tmp = u_path.with_suffix(".parquet.tmp")
            pq.write_table(table, tmp, compression="zstd")
            tmp.replace(u_path)

        meta = {
            "ingest_run_id": ingest_run_id,
            "markets_requested": stats.markets_requested,
            "markets_ok": stats.markets_ok,
            "markets_empty": stats.markets_empty,
            "markets_partial": stats.markets_partial,
            "errors": stats.errors,
            "host": host,
            "fidelity": fidelity,
            "interval": interval,
            "status": "complete" if not stats.errors else "partial",
        }
        (archive / "ingest_metadata.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

    return stats


def asdict_stats(stats: IngestStats) -> dict[str, Any]:
    d = asdict(stats)
    return d
