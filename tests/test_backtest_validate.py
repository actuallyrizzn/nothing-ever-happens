import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from bot.backtest.validate import validate_archive, write_validate_report


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
