"""Unit + integration-style coverage for compare, io_util, historical, clob_prices, calibrate."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from bot.backtest.calibrate import run_tier_a_calibration
from bot.backtest.clob_prices import (
    best_ask_from_book_raw,
    fetch_order_book_raw,
    fetch_prices_history,
    history_to_points,
    sleep_backoff,
)
from bot.backtest.compare import build_compare_html, write_compare_report
from bot.backtest.historical import TierAParquetSource, TierBParquetSource
from bot.backtest.io_util import ArchiveFileLock, iter_jsonl
from bot.backtest.run_context import build_price_context, fee_usd
from bot.backtest.strategy_loop_sim import first_executable_moment_strategy_loop
from bot.backtest.first_hit import first_executable_moment
from bot.backtest.predicate import WalletState
from bot.backtest.spread_model import SpreadModelV0
from bot.config import NothingHappensConfig


@pytest.mark.unit
def test_build_compare_html_and_write_compare_report(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "summary.json").write_text(
        json.dumps({"fidelity_tier": "A", "markets_total": 1, "pnl_usd_sum_where_outcome_known": 0.0}),
        encoding="utf-8",
    )
    (b / "summary.json").write_text(
        json.dumps({"fidelity_tier": "B", "markets_total": 2, "pnl_usd_sum_where_outcome_known": 1.0}),
        encoding="utf-8",
    )
    (a / "run_manifest.json").write_text(json.dumps({"half_spread": 0.01, "fee_bps": 0}), encoding="utf-8")
    out = tmp_path / "cmp.html"
    write_compare_report(run_dir_a=a, run_dir_b=b, out_html=out)
    assert out.exists()
    html = build_compare_html(
        summary_a={"fidelity_tier": "A"},
        summary_b={"fidelity_tier": "B"},
        manifest_a=None,
        manifest_b=None,
    )
    assert "Backtest comparison" in html


@pytest.mark.unit
def test_iter_jsonl_skips_blanks_and_non_dicts(tmp_path: Path) -> None:
    p = tmp_path / "u.jsonl"
    p.write_text('{"a":1}\n\n[1,2]\n{"b":2}\n', encoding="utf-8")
    rows = list(iter_jsonl(p))
    assert rows == [{"a": 1}, {"b": 2}]


@pytest.mark.unit
def test_archive_file_lock(tmp_path: Path) -> None:
    with ArchiveFileLock(tmp_path, "t.lock"):
        assert (tmp_path / "t.lock").exists()


@pytest.mark.unit
def test_tier_a_b_parquet_sources(tmp_path: Path) -> None:
    arc = tmp_path / "arc"
    (arc / "prices").mkdir(parents=True)
    tok = "abc"
    t = pa.table({"t": [1, 2], "p": [0.4, 0.5]})
    pq.write_table(t, arc / "prices" / f"{tok}.parquet")
    src_a = TierAParquetSource(arc)
    assert src_a.load_no_ask_series(tok) == [(1, 0.4), (2, 0.5)]
    assert src_a.load_no_ask_series("missing") == []

    l2 = tmp_path / "l2"
    l2.mkdir()
    t2 = pa.table({"t": [10], "best_ask": [0.55]})
    pq.write_table(t2, l2 / f"{tok}.parquet")
    src_b = TierBParquetSource(l2)
    assert src_b.load_no_ask_series(tok) == [(10, 0.55)]


@pytest.mark.unit
def test_build_price_context_and_fee_usd(tmp_path: Path) -> None:
    cfg = NothingHappensConfig()
    sp = SpreadModelV0(half_spread=0.01)
    ctx_a = build_price_context(
        archive=tmp_path,
        fidelity_tier="A",
        l2_archive=None,
        cfg=cfg,
        spread=sp,
        risk=None,
        fee_bps=10.0,
    )
    assert ctx_a.l2_direct is False
    assert fee_usd(100.0, 10.0) == pytest.approx(0.1)
    assert fee_usd(-1.0, 10.0) == 0.0

    l2 = tmp_path / "l2d"
    l2.mkdir()
    ctx_b = build_price_context(
        archive=tmp_path,
        fidelity_tier="B",
        l2_archive=l2,
        cfg=cfg,
        spread=sp,
        risk=None,
        fee_bps=0.0,
    )
    assert ctx_b.l2_direct is True

    with pytest.raises(ValueError, match="Tier B requires"):
        build_price_context(
            archive=tmp_path,
            fidelity_tier="B",
            l2_archive=None,
            cfg=cfg,
            spread=sp,
            risk=None,
            fee_bps=0.0,
        )
    nf = tmp_path / "notadir"
    nf.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        build_price_context(
            archive=tmp_path,
            fidelity_tier="B",
            l2_archive=nf,
            cfg=cfg,
            spread=sp,
            risk=None,
            fee_bps=0.0,
        )
    with pytest.raises(ValueError, match="Unknown fidelity tier"):
        build_price_context(
            archive=tmp_path,
            fidelity_tier="Z",
            l2_archive=None,
            cfg=cfg,
            spread=sp,
            risk=None,
            fee_bps=0.0,
        )


@pytest.mark.unit
def test_first_hit_last_reason_and_strategy_loop_empty() -> None:
    cfg = NothingHappensConfig(max_entry_price=0.01)
    w = WalletState(cash_usd=10_000.0)
    sp = SpreadModelV0(half_spread=0.01)
    r = first_executable_moment(
        [(1, 0.5), (2, 0.6)],
        cfg=cfg,
        wallet=w,
        spread=sp,
        market_min_order_size=0.01,
        book_min_order_size=0.01,
    )
    assert r.reason_skip in {"predicate_never_true", "above_max_entry"}

    r2 = first_executable_moment_strategy_loop(
        [],
        cfg=cfg,
        wallet=w,
        spread=sp,
        market_min_order_size=0.01,
        book_min_order_size=0.01,
        assume_infinite_book_depth=True,
        safe_notional_usd=None,
    )
    assert r2.reason_skip == "empty_series"


@pytest.mark.unit
def test_strategy_loop_skip_bars_and_l2_direct() -> None:
    cfg = NothingHappensConfig(max_entry_price=0.01, order_dispatch_interval_sec=10)
    w = WalletState(cash_usd=10_000.0)
    sp = SpreadModelV0(half_spread=0.01)
    pts = [(100, 0.5), (105, 0.51), (120, 0.52)]
    r = first_executable_moment_strategy_loop(
        pts,
        cfg=cfg,
        wallet=w,
        spread=sp,
        market_min_order_size=0.01,
        book_min_order_size=0.01,
        assume_infinite_book_depth=True,
        safe_notional_usd=None,
        use_l2_best_ask_direct=True,
    )
    assert r.reason_skip in {"predicate_never_true", "above_max_entry"}


class _Resp:
    def __init__(self, body: bytes, code: int = 200):
        self._body = body
        self.code = code

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


@pytest.mark.unit
def test_fetch_order_book_raw_success_and_errors() -> None:
    body = json.dumps({"asks": [{"price": "0.6"}, {"price": "0.5"}]}).encode()
    with patch("urllib.request.urlopen", return_value=_Resp(body)) as up:
        raw = fetch_order_book_raw(host="https://h", token_id="t1")
    up.assert_called_once()
    assert best_ask_from_book_raw(raw) == 0.5
    assert best_ask_from_book_raw({"asks": []}) is None
    assert best_ask_from_book_raw({"asks": [{"n": 1}]}) is None
    assert best_ask_from_book_raw({"asks": [{"price": "x"}]}) is None

    err = urllib.error.HTTPError("u", 500, "m", hdrs={}, fp=io.BytesIO())
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            fetch_order_book_raw(host="https://h", token_id="t1")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("e")):
        with pytest.raises(RuntimeError, match="network"):
            fetch_order_book_raw(host="https://h", token_id="t1")
    body_bad = json.dumps([1, 2]).encode()
    with patch("urllib.request.urlopen", return_value=_Resp(body_bad)):
        with pytest.raises(ValueError, match="expected object"):
            fetch_order_book_raw(host="https://h", token_id="t1")


@pytest.mark.unit
def test_fetch_prices_history_paths() -> None:
    ok = json.dumps({"history": [{"t": 1, "p": 0.5}, "skip", {"t": 2, "p": 0.4}]}).encode()
    with patch("urllib.request.urlopen", return_value=_Resp(ok)):
        rows = fetch_prices_history(
            host="https://h",
            token_id="t1",
            start_ts=1,
            end_ts=9,
            fidelity=2,
            interval="1h",
        )
    assert history_to_points(rows) == [(1, 0.5), (2, 0.4)]

    empty_hist = json.dumps({"history": None}).encode()
    with patch("urllib.request.urlopen", return_value=_Resp(empty_hist)):
        assert fetch_prices_history(host="https://h", token_id="t1") == []

    bad_hist = json.dumps({"history": {}}).encode()
    with patch("urllib.request.urlopen", return_value=_Resp(bad_hist)):
        with pytest.raises(ValueError, match="must be a list"):
            fetch_prices_history(host="https://h", token_id="t1")

    top_list = json.dumps([]).encode()
    with patch("urllib.request.urlopen", return_value=_Resp(top_list)):
        with pytest.raises(ValueError, match="expected object"):
            fetch_prices_history(host="https://h", token_id="t1")

    http_e = urllib.error.HTTPError("u", 404, "n", hdrs={}, fp=io.BytesIO(b"body"))
    with patch("urllib.request.urlopen", side_effect=http_e):
        with pytest.raises(RuntimeError, match="prices-history HTTP"):
            fetch_prices_history(host="https://h", token_id="t1")


@pytest.mark.unit
def test_history_to_points_filters_bad_rows() -> None:
    assert history_to_points([{}, {"t": "x", "p": 1}, {"t": 1, "p": 0.5}]) == [(1, 0.5)]
    assert history_to_points([{"t": 2, "p": 0.1}, {"t": 1, "p": 0.2}]) == [(1, 0.2), (2, 0.1)]


@pytest.mark.unit
def test_sleep_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr("bot.backtest.clob_prices.time.sleep", fake_sleep)
    monkeypatch.setattr("bot.backtest.clob_prices.random.uniform", lambda _a, _b: 0.0)
    sleep_backoff(2)
    assert sleeps and sleeps[0] > 0


@pytest.mark.unit
def test_run_tier_a_calibration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bot.backtest.calibrate.time.sleep", lambda _s: None)

    def fake_hist(**kwargs: object) -> list[dict]:
        return [{"t": 1, "p": 0.55}]

    def fake_book(**kwargs: object) -> dict:
        return {"asks": [{"price": "0.50"}], "timestamp": 123}

    with (
        patch("bot.backtest.calibrate.fetch_prices_history", side_effect=fake_hist),
        patch("bot.backtest.calibrate.fetch_order_book_raw", side_effect=fake_book),
    ):
        payload = run_tier_a_calibration(host="https://h", token_ids=["a", " ", ""], half_spread=0.01)
    assert payload["samples"]
    jpath = tmp_path / "c.json"
    with (
        patch("bot.backtest.calibrate.fetch_prices_history", side_effect=fake_hist),
        patch("bot.backtest.calibrate.fetch_order_book_raw", side_effect=fake_book),
    ):
        run_tier_a_calibration(host="https://h", token_ids=["b"], half_spread=0.01, out_json=jpath)
    assert jpath.exists()


@pytest.mark.unit
def test_run_tier_a_calibration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.backtest.calibrate.time.sleep", lambda _s: None)

    with patch("bot.backtest.calibrate.fetch_prices_history", return_value=[]):
        p = run_tier_a_calibration(host="https://h", token_ids=["x"], half_spread=0.01)
        assert any("empty_history" in e for e in p["errors"])

    with (
        patch("bot.backtest.calibrate.fetch_prices_history", return_value=[{"t": 1, "p": 0.5}]),
        patch("bot.backtest.calibrate.fetch_order_book_raw", return_value={"asks": []}),
    ):
        p2 = run_tier_a_calibration(host="https://h", token_ids=["y"], half_spread=0.01)
        assert any("no_asks_in_book" in e for e in p2["errors"])

    with (
        patch("bot.backtest.calibrate.fetch_prices_history", side_effect=RuntimeError("boom")),
    ):
        p3 = run_tier_a_calibration(host="https://h", token_ids=["z"], half_spread=0.01)
        assert any("boom" in e for e in p3["errors"])
