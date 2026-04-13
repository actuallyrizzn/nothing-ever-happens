"""Coverage for ``python -m bot.backtest`` CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.backtest import __main__ as bt_main


@pytest.mark.unit
def test_cli_validate_writes_report(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    arc.mkdir()
    (arc / "universe.parquet").write_bytes(b"")
    with patch("bot.backtest.__main__.validate_archive") as v, patch("bot.backtest.__main__.write_validate_report") as w:
        v.return_value = MagicMock(ok=True, errors=[], warnings=[])
        code = bt_main.main(["validate", "--archive", str(arc)])
    assert code == 0
    v.assert_called_once()
    w.assert_called_once()


@pytest.mark.unit
def test_cli_validate_fail_exit_code(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    arc.mkdir()
    with patch("bot.backtest.__main__.validate_archive") as v, patch("bot.backtest.__main__.write_validate_report"):
        v.return_value = MagicMock(ok=False, errors=["e"], warnings=[])
        code = bt_main.main(["validate", "--archive", str(arc)])
    assert code == 2


@pytest.mark.unit
def test_cli_ingest_exit_codes(tmp_path: Path) -> None:
    stats_ok = MagicMock(errors=[])
    stats_bad = MagicMock(errors=["fetch_failed"])
    with patch("bot.backtest.__main__.run_ingest", return_value=stats_ok), patch("bot.backtest.__main__.asdict_stats", return_value={}):
        assert bt_main.main(["ingest", "--archive", str(tmp_path / "a"), "--universe", str(tmp_path / "u.jsonl")]) == 0
    with patch("bot.backtest.__main__.run_ingest", return_value=stats_bad), patch("bot.backtest.__main__.asdict_stats", return_value={}):
        assert bt_main.main(["ingest", "--archive", str(tmp_path / "a"), "--universe", str(tmp_path / "u.jsonl")]) == 1


@pytest.mark.unit
def test_cli_calibrate_and_compare(tmp_path: Path) -> None:
    with patch("bot.backtest.__main__.run_tier_a_calibration", return_value={"errors": [], "samples": []}):
        assert bt_main.main(["calibrate", "--tokens", "a,b"]) == 0
    with patch("bot.backtest.__main__.run_tier_a_calibration", return_value={"errors": ["x"], "samples": []}):
        assert bt_main.main(["calibrate", "--tokens", "a"]) == 1

    ra = tmp_path / "ra"
    rb = tmp_path / "rb"
    ra.mkdir()
    rb.mkdir()
    (ra / "summary.json").write_text(json.dumps({"fidelity_tier": "A"}), encoding="utf-8")
    (rb / "summary.json").write_text(json.dumps({"fidelity_tier": "B"}), encoding="utf-8")
    out_html = tmp_path / "x.html"
    assert bt_main.main(["compare", "--run-a", str(ra), "--run-b", str(rb), "--out-html", str(out_html)]) == 0
    assert out_html.exists()


@pytest.mark.unit
def test_cli_run_success_and_error(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    outd = tmp_path / "out"
    arc.mkdir()
    with patch("bot.backtest.__main__.run_backtest", return_value={"ok": True}):
        assert bt_main.main(["run", "--archive", str(arc), "--out", str(outd)]) == 0
    with patch("bot.backtest.__main__.run_backtest", side_effect=FileNotFoundError("missing")):
        assert bt_main.main(["run", "--archive", str(arc), "--out", str(outd)]) == 4


@pytest.mark.integration
def test_cli_module_validate_subprocess(tmp_path: Path) -> None:
    import importlib

    golden = importlib.import_module("test_backtest_golden")
    _write_minimal_universe = golden._write_minimal_universe
    _write_prices = golden._write_prices

    arc = tmp_path / "arc_sub"
    arc.mkdir()
    tok = "tok_cli_sub"
    _write_prices(arc, tok, [(1_700_000_000, 0.5)])
    _write_minimal_universe(
        arc,
        [
            {
                "slug": "s",
                "no_token_id": tok,
                "yes_token_id": None,
                "condition_id": "c",
                "t_open": 1_700_000_000,
                "t_open_source": "first_history_bar",
                "t_end": 0,
                "outcome_no_wins": True,
                "resolution_status": "resolved",
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
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "bot.backtest", "validate", "--archive", str(arc)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
