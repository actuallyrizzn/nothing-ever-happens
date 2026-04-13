import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from bot.backtest.validate import load_validate_report, validate_archive, write_validate_report


def test_validate_detects_non_monotonic(tmp_path: Path) -> None:
    archive = tmp_path / "arc"
    (archive / "prices").mkdir(parents=True)
    tok = "abc123"
    table = pa.table(
        {
            "token_id": [tok, tok],
            "t": [1_700_000_200, 1_700_000_100],
            "p": [0.5, 0.4],
            "ingest_run_id": ["x", "x"],
            "source": ["clob_prices_history"] * 2,
        }
    )
    pq.write_table(table, archive / "prices" / f"{tok}.parquet")
    uni = pa.table(
        {
            "slug": ["m"],
            "no_token_id": [tok],
            "yes_token_id": [None],
            "condition_id": [""],
            "t_open": [1_700_000_000],
            "t_open_source": ["first_history_bar"],
            "t_end": [0],
            "outcome_no_wins": [True],
            "resolution_status": ["resolved"],
            "gamma_snapshot_utc": [""],
            "ingest_version": ["1"],
            "coverage_class": ["ok"],
            "bar_count": [2],
            "min_order_size": [0.0],
        }
    )
    pq.write_table(uni, archive / "universe.parquet")

    report = validate_archive(archive)
    assert report.ok is False
    assert any("non_monotonic" in e for e in report.errors)


def test_validate_detects_duplicate_timestamp(tmp_path: Path) -> None:
    archive = tmp_path / "arc"
    (archive / "prices").mkdir(parents=True)
    tok = "dup"
    table = pa.table(
        {
            "token_id": [tok, tok],
            "t": [1_700_000_000, 1_700_000_000],
            "p": [0.5, 0.4],
            "ingest_run_id": ["x", "x"],
            "source": ["clob_prices_history"] * 2,
        }
    )
    pq.write_table(table, archive / "prices" / f"{tok}.parquet")
    uni = pa.table(
        {
            "slug": ["m"],
            "no_token_id": [tok],
            "yes_token_id": [None],
            "condition_id": [""],
            "t_open": [1_700_000_000],
            "t_open_source": ["first_history_bar"],
            "t_end": [0],
            "outcome_no_wins": [None],
            "resolution_status": ["unknown"],
            "gamma_snapshot_utc": [""],
            "ingest_version": ["1"],
            "coverage_class": ["ok"],
            "bar_count": [2],
            "min_order_size": [0.0],
        }
    )
    pq.write_table(uni, archive / "universe.parquet")
    report = validate_archive(archive)
    assert report.ok is False
    assert any("duplicate_t" in e for e in report.errors)


def test_validate_ok_minimal(tmp_path: Path) -> None:
    archive = tmp_path / "arc"
    (archive / "prices").mkdir(parents=True)
    tok = "tok1"
    table = pa.table(
        {
            "token_id": [tok],
            "t": [1_700_000_000],
            "p": [0.5],
            "ingest_run_id": ["x"],
            "source": ["clob_prices_history"],
        }
    )
    pq.write_table(table, archive / "prices" / f"{tok}.parquet")
    uni = pa.table(
        {
            "slug": ["m"],
            "no_token_id": [tok],
            "yes_token_id": [None],
            "condition_id": [""],
            "t_open": [1_700_000_000],
            "t_open_source": ["first_history_bar"],
            "t_end": [0],
            "outcome_no_wins": [None],
            "resolution_status": ["unknown"],
            "gamma_snapshot_utc": [""],
            "ingest_version": ["1"],
            "coverage_class": ["ok"],
            "bar_count": [1],
            "min_order_size": [0.0],
        }
    )
    pq.write_table(uni, archive / "universe.parquet")
    report = validate_archive(archive)
    assert report.ok is True
    write_validate_report(archive, report)
    data = json.loads((archive / "validate_report.json").read_text())
    assert data["ok"] is True


def test_validate_missing_universe(tmp_path: Path) -> None:
    arc = tmp_path / "nu"
    arc.mkdir()
    r = validate_archive(arc)
    assert r.ok is False
    assert "missing_universe_parquet" in r.errors


def test_validate_universe_missing_no_token_column(tmp_path: Path) -> None:
    arc = tmp_path / "ntcol"
    arc.mkdir()
    pq.write_table(pa.table({"x": [1]}), arc / "universe.parquet")
    r = validate_archive(arc)
    assert r.ok is False
    assert any("no_token_id" in e for e in r.errors)


def test_validate_suspicious_timestamp_unit(tmp_path: Path) -> None:
    arc = tmp_path / "susp"
    (arc / "prices").mkdir(parents=True)
    tok = "t1"
    pq.write_table(
        pa.table(
            {
                "token_id": [tok],
                "t": [500],
                "p": [0.5],
                "ingest_run_id": ["x"],
                "source": ["clob_prices_history"],
            }
        ),
        arc / "prices" / f"{tok}.parquet",
    )
    uni = pa.table(
        {
            "slug": ["m"],
            "no_token_id": [tok],
            "yes_token_id": [None],
            "condition_id": [""],
            "t_open": [500],
            "t_open_source": ["first_history_bar"],
            "t_end": [0],
            "outcome_no_wins": [True],
            "resolution_status": ["resolved"],
            "gamma_snapshot_utc": [""],
            "ingest_version": ["1"],
            "coverage_class": ["ok"],
            "bar_count": [1],
            "min_order_size": [0.0],
        }
    )
    pq.write_table(uni, arc / "universe.parquet")
    r = validate_archive(arc)
    assert r.ok is False
    assert any("suspicious_t_unit" in e for e in r.errors)


def test_validate_coverage_mismatch_empty_file(tmp_path: Path) -> None:
    arc = tmp_path / "cme"
    (arc / "prices").mkdir(parents=True)
    tok = "e1"
    pq.write_table(
        pa.table(
            {
                "token_id": pa.array([], type=pa.string()),
                "t": pa.array([], type=pa.int64()),
                "p": pa.array([], type=pa.float64()),
                "ingest_run_id": pa.array([], type=pa.string()),
                "source": pa.array([], type=pa.string()),
            }
        ),
        arc / "prices" / f"{tok}.parquet",
    )
    uni = pa.table(
        {
            "slug": ["m"],
            "no_token_id": [tok],
            "yes_token_id": [None],
            "condition_id": [""],
            "t_open": [1_700_000_000],
            "t_open_source": ["first_history_bar"],
            "t_end": [0],
            "outcome_no_wins": [True],
            "resolution_status": ["resolved"],
            "gamma_snapshot_utc": [""],
            "ingest_version": ["1"],
            "coverage_class": ["ok"],
            "bar_count": [0],
            "min_order_size": [0.0],
        }
    )
    pq.write_table(uni, arc / "universe.parquet")
    r = validate_archive(arc)
    assert any("coverage_mismatch_empty_file" in w for w in r.warnings)


def test_validate_partial_range_vs_ingest_window(tmp_path: Path) -> None:
    arc = tmp_path / "pr"
    (arc / "prices").mkdir(parents=True)
    tok = "p1"
    pq.write_table(
        pa.table(
            {
                "token_id": [tok, tok],
                "t": [1_700_000_000, 1_700_000_060],
                "p": [0.5, 0.4],
                "ingest_run_id": ["x", "x"],
                "source": ["clob_prices_history", "clob_prices_history"],
            }
        ),
        arc / "prices" / f"{tok}.parquet",
    )
    uni = pa.table(
        {
            "slug": ["m"],
            "no_token_id": [tok],
            "yes_token_id": [None],
            "condition_id": [""],
            "t_open": [1_700_000_000],
            "t_open_source": ["first_history_bar"],
            "t_end": [0],
            "outcome_no_wins": [True],
            "resolution_status": ["resolved"],
            "gamma_snapshot_utc": [""],
            "ingest_version": ["1"],
            "coverage_class": ["ok"],
            "bar_count": [2],
            "min_order_size": [0.0],
            "ingest_start_ts": [1_699_000_000],
            "ingest_end_ts": [1_701_000_000],
        }
    )
    pq.write_table(uni, arc / "universe.parquet")
    r = validate_archive(arc)
    assert any("partial_range_vs_ingest_window" in w for w in r.warnings)


def test_load_validate_report_missing_and_bad_json(tmp_path: Path) -> None:
    arc = tmp_path / "lr"
    arc.mkdir()
    assert load_validate_report(arc) is None
    (arc / "validate_report.json").write_text("{", encoding="utf-8")
    assert load_validate_report(arc) is None
