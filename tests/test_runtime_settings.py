"""Tests for DB-backed runtime settings."""

from __future__ import annotations

import os
from pathlib import Path

import sqlalchemy as sa

from bot.db import create_engine, create_tables, runtime_settings_table
from bot.runtime_settings import (
    apply_runtime_settings,
    load_stored_settings,
    save_settings_from_form,
    seed_runtime_settings_if_empty,
    validate_all_settings,
)


def test_seed_and_apply_roundtrip(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "t.sqlite"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    create_tables(engine)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_MODE", raising=False)
    monkeypatch.delenv("PM_NH_CASH_PCT_PER_TRADE", raising=False)
    seed_runtime_settings_if_empty(engine)
    rows = load_stored_settings(engine)
    assert rows["BOT_MODE"] == "paper"
    assert "PM_NH_CASH_PCT_PER_TRADE" in rows
    n = apply_runtime_settings(engine)
    assert n > 0
    assert os.environ["BOT_MODE"] == "paper"


def test_validate_all_settings_live_requires_key() -> None:
    data = {
        "BOT_MODE": "live",
        "DRY_RUN": "false",
        "LIVE_TRADING_ENABLED": "true",
        "PM_CONNECTION_HOST": "https://clob.polymarket.com",
        "PM_CONNECTION_CHAIN_ID": "137",
        "PM_CONNECTION_SIGNATURE_TYPE": "2",
        "PRIVATE_KEY": "",
        "FUNDER_ADDRESS": "0x0000000000000000000000000000000000000001",
        "POLYGON_RPC_URL": "https://polygon.example/rpc",
        "TRADE_LEDGER_PATH": "trades.jsonl",
        "LOG_LEVEL": "INFO",
        "PM_BACKGROUND_EXECUTOR_WORKERS": "4",
        "PM_NH_MARKET_REFRESH_INTERVAL_SEC": "600",
        "PM_NH_PRICE_POLL_INTERVAL_SEC": "60",
        "PM_NH_POSITION_SYNC_INTERVAL_SEC": "60",
        "PM_NH_ORDER_DISPATCH_INTERVAL_SEC": "60",
        "PM_NH_CASH_PCT_PER_TRADE": "0.02",
        "PM_NH_MIN_TRADE_AMOUNT": "5",
        "PM_NH_FIXED_TRADE_AMOUNT_USD": "0",
        "PM_NH_MAX_ENTRY_PRICE": "0.65",
        "PM_NH_ALLOWED_SLIPPAGE": "0.3",
        "PM_NH_REQUEST_CONCURRENCY": "4",
        "PM_NH_BUY_RETRY_COUNT": "3",
        "PM_NH_BUY_RETRY_BASE_DELAY_SEC": "1",
        "PM_NH_MAX_BACKOFF_SEC": "900",
        "PM_NH_MAX_NEW_POSITIONS": "-1",
        "PM_NH_SHUTDOWN_ON_MAX_NEW_POSITIONS": "false",
        "PM_NH_REDEEMER_INTERVAL_SEC": "1800",
        "PM_RISK_MAX_TOTAL_OPEN_EXPOSURE_USD": "1500",
        "PM_RISK_MAX_MARKET_OPEN_EXPOSURE_USD": "1000",
        "PM_RISK_MAX_DAILY_DRAWDOWN_USD": "0",
        "PM_RISK_KILL_COOLDOWN_SEC": "900",
        "PM_RISK_DRAWDOWN_ARM_AFTER_SEC": "1800",
        "PM_RISK_DRAWDOWN_MIN_FRESH_OBS": "3",
    }
    ok, msg = validate_all_settings(data)
    assert ok is False
    assert "PRIVATE_KEY" in msg or "private" in msg.lower()


def test_save_preserves_secret_when_blank(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "t.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    create_tables(engine)
    monkeypatch.chdir(tmp_path)
    seed_runtime_settings_if_empty(engine)
    with engine.begin() as conn:
        conn.execute(
            runtime_settings_table.insert().values(
                key="PRIVATE_KEY", value="0xdeadbeef", updated_at=sa.func.now()
            )
        )
    # No PRIVATE_KEY in POST → unchanged; BOT_MODE omitted → unchanged.
    form: dict[str, str] = {"csrf_token": "x"}
    ok, err = save_settings_from_form(engine, form)
    assert ok, err
    stored = load_stored_settings(engine)
    assert stored["PRIVATE_KEY"] == "0xdeadbeef"
