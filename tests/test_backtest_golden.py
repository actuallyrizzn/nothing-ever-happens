"""Golden expectations for synthetic archives (plan §11 Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from bot.backtest.run import BacktestRunOptions, run_backtest


def _write_minimal_universe(archive: Path, rows: list[dict]) -> None:
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, archive / "universe.parquet", compression="zstd")


def _write_prices(archive: Path, token_id: str, pts: list[tuple[int, float]]) -> None:
    (archive / "prices").mkdir(parents=True, exist_ok=True)
    n = len(pts)
    if n == 0:
        t = pa.table(
            {
                "token_id": pa.array([], type=pa.string()),
                "t": pa.array([], type=pa.int64()),
                "p": pa.array([], type=pa.float64()),
                "ingest_run_id": pa.array([], type=pa.string()),
                "source": pa.array([], type=pa.string()),
            }
        )
    else:
        ts, ps = zip(*pts)
        t = pa.table(
            {
                "token_id": [token_id] * n,
                "t": list(ts),
                "p": list(ps),
                "ingest_run_id": ["g"] * n,
                "source": ["clob_prices_history"] * n,
            }
        )
    pq.write_table(t, archive / "prices" / f"{token_id}.parquet", compression="zstd")


def test_golden_t_first_p1(tmp_path: Path) -> None:
    """Hand-checked: first bar above max_entry (0.5), second bar in range."""
    cfg_path = tmp_path / "nh.json"
    cfg_path.write_text('{"max_entry_price": 0.5}', encoding="utf-8")
    archive = tmp_path / "arc"
    archive.mkdir()
    tok = "tok_golden_1"
    _write_prices(archive, tok, [(1_700_000_000, 0.60), (1_700_000_060, 0.40)])
    _write_minimal_universe(
        archive,
        [
            {
                "slug": "golden1",
                "no_token_id": tok,
                "yes_token_id": None,
                "condition_id": "c1",
                "t_open": 1_700_000_000,
                "t_open_source": "first_history_bar",
                "t_end": 0,
                "outcome_no_wins": True,
                "resolution_status": "resolved",
                "gamma_snapshot_utc": "",
                "ingest_version": "1",
                "coverage_class": "ok",
                "bar_count": 2,
                "min_order_size": 0.0,
                "universe_rule": "fixture",
                "ingest_start_ts": None,
                "ingest_end_ts": None,
                "min_bars_threshold": None,
            }
        ],
    )
    out = tmp_path / "out"
    summary = run_backtest(
        BacktestRunOptions(
            archive=archive,
            out_dir=out,
            config_path=cfg_path,
            half_spread=0.0,
            portfolio_sequencing="single_market_only",
            discretization="P1",
        )
    )
    assert summary["markets_with_entry"] == 1
    import json

    line = (out / "per_market.jsonl").read_text().strip().splitlines()[0]
    row = json.loads(line)
    assert row["t_first"] == 1_700_000_060


def test_void_resolution_excludes_pnl(tmp_path: Path) -> None:
    archive = tmp_path / "arc2"
    archive.mkdir()
    tok = "tok_void"
    _write_prices(archive, tok, [(1_700_000_000, 0.40)])
    _write_minimal_universe(
        archive,
        [
            {
                "slug": "v",
                "no_token_id": tok,
                "yes_token_id": None,
                "condition_id": "c",
                "t_open": 1_700_000_000,
                "t_open_source": "first_history_bar",
                "t_end": 0,
                "outcome_no_wins": True,
                "resolution_status": "void",
                "gamma_snapshot_utc": "",
                "ingest_version": "1",
                "coverage_class": "ok",
                "bar_count": 1,
                "min_order_size": 0.0,
                "universe_rule": "fixture",
                "ingest_start_ts": None,
                "ingest_end_ts": None,
                "min_bars_threshold": None,
            }
        ],
    )
    out = tmp_path / "out2"
    summary = run_backtest(
        BacktestRunOptions(archive=archive, out_dir=out, half_spread=0.0)
    )
    assert summary["markets_with_entry"] == 1
    assert summary["pnl_usd_sum_where_outcome_known"] == 0.0


def test_min_markets_gate_raises(tmp_path: Path) -> None:
    archive = tmp_path / "arc3"
    archive.mkdir()
    tok = "t3"
    _write_prices(archive, tok, [(1_700_000_000, 0.99)])
    _write_minimal_universe(
        archive,
        [
            {
                "slug": "x",
                "no_token_id": tok,
                "yes_token_id": None,
                "condition_id": "c",
                "t_open": 1_700_000_000,
                "t_open_source": "first_history_bar",
                "t_end": 0,
                "outcome_no_wins": None,
                "resolution_status": "unknown",
                "gamma_snapshot_utc": "",
                "ingest_version": "1",
                "coverage_class": "ok",
                "bar_count": 1,
                "min_order_size": 0.0,
                "universe_rule": "fixture",
                "ingest_start_ts": None,
                "ingest_end_ts": None,
                "min_bars_threshold": None,
            }
        ],
    )
    with pytest.raises(ValueError, match="Quality gate"):
        run_backtest(
            BacktestRunOptions(
                archive=archive,
                out_dir=tmp_path / "o3",
                min_markets_with_data=5,
                min_bars_per_market=1,
            )
        )
