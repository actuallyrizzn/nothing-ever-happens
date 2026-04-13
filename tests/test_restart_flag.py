"""Tests for optional restart flag file (cron-driven restart)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.restart_flag import restart_via_flag_enabled, write_restart_flag_after_settings_save


def test_restart_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEH_RESTART_FLAG_PATH", raising=False)
    assert restart_via_flag_enabled() is False
    assert write_restart_flag_after_settings_save() is False


def test_restart_flag_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    flag = tmp_path / ".neh_restart_requested"
    monkeypatch.setenv("NEH_RESTART_FLAG_PATH", str(flag))
    assert restart_via_flag_enabled() is True
    assert write_restart_flag_after_settings_save() is True
    text = flag.read_text(encoding="utf-8")
    assert text.startswith("requested_at=")
