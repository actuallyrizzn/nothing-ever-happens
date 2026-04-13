"""Tests for bot.trade_ledger: dual-output trade recording."""

import json
import logging
import os
import queue
import tempfile
import time

from bot.trade_ledger import flush_trade_ledger, record_order, shutdown_trade_ledger


def test_record_order_logs_to_logger(caplog):
    """record_order emits a structured log record at INFO level."""
    with caplog.at_level(logging.INFO, logger="bot.trade_ledger"):
        record_order(
            action="buy",
            market_slug="btc-5m-test",
            side="UP",
            token_id="tok_123",
            amount=5.0,
            order_id="ord_abc",
            order_status="filled",
        )
        assert flush_trade_ledger()

    # Should have at least one log record with the trade data
    trade_logs = [r for r in caplog.records if r.message == "trade_ledger"]
    assert len(trade_logs) == 1
    rec = trade_logs[0]
    assert rec.action == "buy"
    assert rec.market_slug == "btc-5m-test"
    assert rec.side == "UP"
    assert rec.token_id == "tok_123"
    assert rec.amount == 5.0
    assert rec.order_id == "ord_abc"
    assert rec.order_status == "filled"


def test_record_order_writes_to_file(monkeypatch):
    """record_order also writes JSON-lines to the ledger file."""
    import bot.trade_ledger as tl

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        tmp_path = f.name
    old_fd = tl._ledger_fd
    old_open_path = tl._ledger_open_path
    old_env = os.environ.get("TRADE_LEDGER_PATH")
    try:
        monkeypatch.setenv("TRADE_LEDGER_PATH", tmp_path)
        tl._ledger_fd = None
        tl._ledger_open_path = None

        record_order(
            action="sell",
            market_slug="btc-5m-file",
            side="DOWN",
            token_id="tok_456",
            amount=3.0,
        )
        assert flush_trade_ledger()

        with open(tmp_path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["action"] == "sell"
        assert data["market_slug"] == "btc-5m-file"
        assert data["side"] == "DOWN"
        assert data["amount"] == 3.0
    finally:
        tl._ledger_fd = old_fd
        tl._ledger_open_path = old_open_path
        if old_env is None:
            monkeypatch.delenv("TRADE_LEDGER_PATH", raising=False)
        else:
            monkeypatch.setenv("TRADE_LEDGER_PATH", old_env)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def test_record_order_includes_error_and_extras(caplog):
    """Error field and extra kwargs appear in the log record."""
    with caplog.at_level(logging.INFO, logger="bot.trade_ledger"):
        record_order(
            action="error",
            market_slug="btc-5m-err",
            side="UP",
            token_id="tok_err",
            amount=5.0,
            error="timeout",
            custom_field="custom_value",
        )
        assert flush_trade_ledger()

    trade_logs = [r for r in caplog.records if r.message == "trade_ledger"]
    assert len(trade_logs) == 1
    rec = trade_logs[0]
    assert rec.error == "timeout"
    assert rec.custom_field == "custom_value"


def test_ledger_reopens_when_trade_ledger_path_env_changes(monkeypatch, tmp_path):
    """Writes follow TRADE_LEDGER_PATH after env updates (e.g. runtime_settings applied)."""
    import bot.trade_ledger as tl

    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    monkeypatch.setenv("TRADE_LEDGER_PATH", str(a))
    tl._ledger_fd = None
    tl._ledger_open_path = None
    record_order(
        action="buy",
        market_slug="m1",
        side="NO",
        token_id="t1",
        amount=1.0,
    )
    assert flush_trade_ledger()
    assert a.read_text(encoding="utf-8").strip()
    assert not b.exists()

    monkeypatch.setenv("TRADE_LEDGER_PATH", str(b))
    record_order(
        action="buy",
        market_slug="m2",
        side="NO",
        token_id="t2",
        amount=2.0,
    )
    assert flush_trade_ledger()
    line = b.read_text(encoding="utf-8").strip()
    assert "m2" in line
    assert a.read_text(encoding="utf-8").count("\n") == 1


def test_shutdown_trade_ledger_drains_queued_records(monkeypatch):
    import bot.trade_ledger as tl

    tl.shutdown_trade_ledger(timeout_sec=1.0)
    monkeypatch.setattr(tl, "_ledger_queue", queue.Queue(maxsize=32))
    monkeypatch.setattr(tl, "_writer_thread", None)

    writes: list[str] = []

    def _slow_write(record):
        time.sleep(0.02)
        writes.append(record["order_id"])

    monkeypatch.setattr(tl, "_write_record", _slow_write)

    for i in range(5):
        tl.record_order(
            action="buy",
            market_slug="btc-5m-backlog",
            side="UP",
            token_id="tok_backlog",
            amount=5.0,
            order_id=f"ord_{i}",
            order_status="filled",
        )

    tl.shutdown_trade_ledger(timeout_sec=1.0)
    assert len(writes) == 5
    assert tl._ledger_queue.unfinished_tasks == 0


def teardown_module():
    shutdown_trade_ledger(timeout_sec=1.0)
