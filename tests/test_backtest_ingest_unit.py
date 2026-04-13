"""Unit tests for bot.backtest.ingest helpers and run_ingest branches."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.backtest.ingest import (
    IngestStats,
    SlidingWindowLimiter,
    _load_checkpoint,
    _merge_points,
    _p95,
    _prices_path,
    _read_existing_points,
    _save_checkpoint,
    _write_prices_parquet,
    asdict_stats,
    run_ingest,
)


@pytest.mark.unit
def test_p95_and_checkpoint_roundtrip(tmp_path: Path) -> None:
    assert _p95([]) is None
    assert _p95([1.0, 2.0, 3.0, 4.0, 100.0]) is not None
    arc = tmp_path / "a"
    arc.mkdir()
    _save_checkpoint(arc, {"completed": {"t": "h"}})
    assert _load_checkpoint(arc) == {"completed": {"t": "h"}}
    (arc / "ingest_checkpoint.json").write_text("{not json", encoding="utf-8")
    assert _load_checkpoint(arc) == {}


@pytest.mark.unit
def test_merge_points_and_prices_path() -> None:
    assert _merge_points([(2, 0.5), (1, 0.4)], [(1, 0.6)]) == [(1, 0.6), (2, 0.5)]
    p = _prices_path(Path("/x"), "tid")
    assert p.name == "tid.parquet" and "prices" in p.parts


@pytest.mark.unit
def test_write_prices_parquet_empty_and_nonempty(tmp_path: Path) -> None:
    p = tmp_path / "p.parquet"
    _write_prices_parquet(p, token_id="t", points=[], ingest_run_id="r")
    assert p.exists()
    _write_prices_parquet(p, token_id="t", points=[(1, 0.5), (2, 0.4)], ingest_run_id="r2")
    assert _read_existing_points(p, "t") == [(1, 0.5), (2, 0.4)]


@pytest.mark.unit
def test_sliding_window_limiter_acquire_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    lim = SlidingWindowLimiter(max_events=1, window_sec=10.0)
    sleeps: list[float] = []

    def fake_sleep(d: float) -> None:
        sleeps.append(d)

    clock = [0.0, 0.0, 0.0, 11.0, 11.0]
    idx = {"i": 0}

    def fake_mono() -> float:
        i = idx["i"]
        idx["i"] += 1
        return clock[i]

    monkeypatch.setattr("bot.backtest.ingest.time.sleep", fake_sleep)
    monkeypatch.setattr("bot.backtest.ingest.time.monotonic", fake_mono)
    lim.acquire()
    lim.acquire()
    assert sleeps, "expected throttle sleep"


@pytest.mark.unit
def test_run_ingest_minimal_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    arc = tmp_path / "arch"
    uni = tmp_path / "u.jsonl"
    arc.mkdir()
    tok = "toking1"
    uni.write_text(
        json.dumps(
            {
                "no_token_id": tok,
                "slug": "s",
                "condition_id": "c1",
                "yes_token_id": None,
                "t_end": 0,
                "resolution_status": "resolved",
                "outcome_no_wins": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_fetch(**kwargs: object) -> list[dict]:
        return [{"t": 1_700_000_000, "p": 0.45}, {"t": 1_700_000_060, "p": 0.44}]

    monkeypatch.setattr("bot.backtest.ingest.fetch_prices_history", fake_fetch)
    monkeypatch.setattr("bot.backtest.ingest.sleep_backoff", lambda *_a, **_k: None)

    stats = run_ingest(
        archive=arc,
        universe_path=uni,
        host="https://clob.example",
        max_requests_per_10s=10_000,
        force=True,
        resume=False,
        max_retries=1,
    )
    assert isinstance(stats, IngestStats)
    assert stats.markets_ok >= 1
    d = asdict_stats(stats)
    assert "fetch_latency_p95_sec" in d


@pytest.mark.unit
def test_run_ingest_slug_condition_conflict(tmp_path: Path) -> None:
    arc = tmp_path / "a2"
    uni = tmp_path / "u2.jsonl"
    arc.mkdir()
    uni.write_text(
        json.dumps(
            {
                "no_token_id": "t1",
                "slug": "dup",
                "condition_id": "c1",
            }
        )
        + "\n"
        + json.dumps(
            {
                "no_token_id": "t2",
                "slug": "dup",
                "condition_id": "c2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stats = run_ingest(
        archive=arc,
        universe_path=uni,
        max_requests_per_10s=10_000,
        force=True,
        resume=False,
        max_retries=1,
    )
    assert any("join_mismatch_slug" in e for e in stats.errors)


@pytest.mark.unit
def test_run_ingest_row_missing_token(tmp_path: Path) -> None:
    arc = tmp_path / "a3"
    uni = tmp_path / "u3.jsonl"
    arc.mkdir()
    uni.write_text(json.dumps({"slug": "x"}) + "\n", encoding="utf-8")
    stats = run_ingest(archive=arc, universe_path=uni, force=True, resume=False, max_retries=1)
    assert any("row_missing_no_token_id" in e for e in stats.errors)


@pytest.mark.unit
def test_run_ingest_max_gb_abort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    arc = tmp_path / "a4"
    uni = tmp_path / "u4.jsonl"
    arc.mkdir()
    tok = "tg"
    uni.write_text(
        json.dumps({"no_token_id": tok, "slug": "s", "condition_id": "c"}),
        encoding="utf-8",
    )

    def fake_fetch(**kwargs: object) -> list[dict]:
        return [{"t": 1_700_000_000, "p": 0.5}]

    monkeypatch.setattr("bot.backtest.ingest.fetch_prices_history", fake_fetch)
    monkeypatch.setattr("bot.backtest.ingest.sleep_backoff", lambda *_a, **_k: None)

    stats = run_ingest(
        archive=arc,
        universe_path=uni,
        force=True,
        resume=False,
        max_retries=1,
        max_gb=1e-12,
    )
    assert any("max_gb_exceeded" in e for e in stats.errors)


@pytest.mark.unit
def test_run_ingest_load_universe_parquet_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    arc = tmp_path / "a5"
    uni = tmp_path / "u5.jsonl"
    arc.mkdir()
    bad = arc / "universe.parquet"
    bad.write_bytes(b"not parquet")
    uni.write_text(
        json.dumps({"no_token_id": "z", "slug": "s", "condition_id": "c"}),
        encoding="utf-8",
    )

    def fake_fetch(**kwargs: object) -> list[dict]:
        return [{"t": 1_700_000_000, "p": 0.5}]

    monkeypatch.setattr("bot.backtest.ingest.fetch_prices_history", fake_fetch)
    monkeypatch.setattr("bot.backtest.ingest.sleep_backoff", lambda *_a, **_k: None)
    stats = run_ingest(archive=arc, universe_path=uni, force=True, resume=False, max_retries=1)
    assert any("load_universe_parquet" in e for e in stats.errors)


@pytest.mark.unit
def test_run_ingest_read_existing_points_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    arc = tmp_path / "a6"
    uni = tmp_path / "u6.jsonl"
    arc.mkdir()
    (arc / "prices").mkdir()
    tok = "tbad"
    corrupt = arc / "prices" / f"{tok}.parquet"
    corrupt.write_bytes(b"x")
    uni.write_text(
        json.dumps({"no_token_id": tok, "slug": "s", "condition_id": "c"}),
        encoding="utf-8",
    )

    def fake_fetch(**kwargs: object) -> list[dict]:
        return [{"t": 1_700_000_000, "p": 0.5}]

    monkeypatch.setattr("bot.backtest.ingest.fetch_prices_history", fake_fetch)
    monkeypatch.setattr("bot.backtest.ingest.sleep_backoff", lambda *_a, **_k: None)
    stats = run_ingest(archive=arc, universe_path=uni, force=False, resume=True, max_retries=1)
    assert any("read_existing" in e for e in stats.errors)
