"""Coverage for time_utils, order_status, latency, logging_config."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from bot import latency as latency_mod
from bot.logging_config import configure_logging
from bot.order_status import normalize_optional_order_status, normalize_order_status
from bot.time_utils import parse_venue_timestamp, to_epoch_seconds


@pytest.mark.unit
def test_parse_venue_timestamp_variants() -> None:
    assert parse_venue_timestamp(None) is None
    assert parse_venue_timestamp("") is None
    assert parse_venue_timestamp("   ") is None
    assert parse_venue_timestamp(1_700_000_000) is not None
    assert parse_venue_timestamp(1_700_000_000_000) is not None
    assert parse_venue_timestamp("1700000000") is not None
    assert parse_venue_timestamp("not-a-date") is None
    dt_naive = datetime(2024, 1, 2, 3, 4, 5)
    assert parse_venue_timestamp(dt_naive.isoformat()) is not None
    dt_aware = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert parse_venue_timestamp(dt_aware.isoformat()) is not None


@pytest.mark.unit
def test_to_epoch_seconds() -> None:
    assert to_epoch_seconds(None) is None
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert to_epoch_seconds(dt) == int(dt.timestamp())
    assert to_epoch_seconds(dt.replace(tzinfo=None)) is not None
    assert to_epoch_seconds("invalid") is None
    assert to_epoch_seconds("1700000000") == 1_700_000_000


@pytest.mark.unit
def test_order_status_normalization() -> None:
    assert normalize_order_status("PARTIAL") == "partially_filled"
    assert normalize_order_status("unknown_custom") == "unknown_custom"
    assert normalize_optional_order_status(None) is None
    assert normalize_optional_order_status("  ") is None


@pytest.mark.unit
def test_latency_helpers(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    assert latency_mod.monotonic_us() > 0
    monkeypatch.setenv("BOT_VARIANT", "test_variant")
    with caplog.at_level(logging.INFO, logger="bot.latency"):
        latency_mod.log_latency_event("m1", extra_key=1)
        latency_mod.log_latency_span("m2", 100, 250, foo="bar")
    assert any("latency_event" in r.message for r in caplog.records)


@pytest.mark.unit
def test_configure_logging_levels() -> None:
    configure_logging("DEBUG")
    configure_logging("bogus_level_xyz")
    root = logging.getLogger()
    assert root.handlers
