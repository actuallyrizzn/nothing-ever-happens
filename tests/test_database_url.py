"""SQLite-only database URL resolution."""

import pytest

from bot.db import reject_non_sqlite_database_url, resolve_database_url


def test_reject_postgres_urls():
    with pytest.raises(ValueError, match="PostgreSQL is not supported"):
        reject_non_sqlite_database_url("postgresql://localhost/db")
    with pytest.raises(ValueError, match="PostgreSQL is not supported"):
        reject_non_sqlite_database_url("postgres://localhost/db")


def test_resolve_default_sqlite_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("NOTHING_HAPPENS_SQLITE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    url = resolve_database_url()
    assert url.startswith("sqlite:///")
    assert str(tmp_path) in url.replace("sqlite:///", "")


def test_resolve_explicit_sqlite_url(monkeypatch, tmp_path):
    p = tmp_path / "custom.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{p}")
    assert resolve_database_url() == f"sqlite:///{p}"


def test_resolve_sqlite_path_env(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sub = tmp_path / "data"
    sub.mkdir()
    monkeypatch.setenv("NOTHING_HAPPENS_SQLITE_PATH", str(sub / "bot.sqlite"))
    url = resolve_database_url()
    assert "bot.sqlite" in url
