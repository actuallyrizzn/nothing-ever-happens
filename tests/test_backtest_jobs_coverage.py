"""Coverage for dashboard backtest job queue."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
import pytest

from bot.backtest import jobs as jobs_mod
from bot.backtest.jobs import BacktestJobQueue
from bot.dashboard_auth import SESSION_COOKIE, DashboardAuth


@pytest.fixture
def auth_setup(tmp_path: Path) -> tuple[DashboardAuth, str]:
    secret = "x" * 32
    db = str(tmp_path / "dash.sqlite")
    auth = DashboardAuth(secret, db)
    auth.create_user("jobuser", "password123")
    token, _ = auth.sign_session(1)
    sess = auth.read_session(token)
    assert sess is not None
    return auth, token


@pytest.mark.asyncio
@pytest.mark.integration
async def test_jobs_no_auth_enqueue_and_poll(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BACKTEST_ENFORCE_LOCAL_ONLY", "0")
    q = BacktestJobQueue(auth=None)
    q._job_root = tmp_path / "jobs"  # type: ignore[misc]

    async def fake_finalize(self: BacktestJobQueue, job_id: str, opts: object) -> None:
        self._jobs[job_id]["status"] = "done"
        self._jobs[job_id]["summary"] = {"x": 1}
        async with self._lock:
            self._running = max(0, self._running - 1)

    monkeypatch.setattr(BacktestJobQueue, "_finalize_job", fake_finalize)

    app = aiohttp.web.Application()
    q.register_routes(app)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/admin/backtest") as r:
                assert r.status == 200
                body = await r.text()
                assert "Backtest" in body
            async with session.get(f"http://127.0.0.1:{port}/api/backtest/datasets") as r2:
                d = await r2.json()
                assert "datasets" in d
            payload = {"archive": str(tmp_path), "csrf_token": ""}
            async with session.post(
                f"http://127.0.0.1:{port}/api/backtest/jobs",
                json=payload,
            ) as r3:
                out = await r3.json()
                assert r3.status == 202
                jid = out["job_id"]
            async with session.get(f"http://127.0.0.1:{port}/api/backtest/jobs/{jid}") as r4:
                st = await r4.json()
                assert st["status"] == "done"
            async with session.get(f"http://127.0.0.1:{port}/api/backtest/jobs/missing") as r5:
                assert r5.status == 404
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_jobs_csrf_and_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, auth_setup) -> None:
    auth, token = auth_setup
    monkeypatch.setenv("BACKTEST_ENFORCE_LOCAL_ONLY", "1")
    q = BacktestJobQueue(auth=auth)
    q._job_root = tmp_path / "jr"
    app = aiohttp.web.Application()
    q.register_routes(app)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            cookies = {SESSION_COOKIE: token}
            async with session.post(
                f"http://127.0.0.1:{port}/api/backtest/jobs",
                json={"archive": "/tmp", "csrf_token": "wrong"},
                cookies=cookies,
            ) as r:
                assert r.status == 403
            sess = auth.read_session(token)
            assert sess is not None
            async with session.post(
                f"http://127.0.0.1:{port}/api/backtest/jobs",
                data="not-json",
                headers={"Content-Type": "application/json"},
                cookies=cookies,
            ) as r2:
                assert r2.status == 400
            async with session.post(
                f"http://127.0.0.1:{port}/api/backtest/jobs",
                json={"archive": "/tmp", "csrf_token": sess.csrf, "config_json": "https://evil"},
                cookies=cookies,
            ) as r3:
                assert r3.status == 400
    finally:
        await runner.cleanup()


@pytest.mark.unit
def test_datasets_from_env_json_and_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "BACKTEST_DATASETS_JSON",
        json.dumps([{"id": "a", "path": "/p", "label": "A"}, {"bad": True}, {"id": "b", "path": "/q", "label": "B"}]),
    )
    monkeypatch.delenv("BACKTEST_ARCHIVE_ROOT", raising=False)
    ds = jobs_mod._datasets_from_env()
    assert len(ds) == 2

    monkeypatch.delenv("BACKTEST_DATASETS_JSON", raising=False)
    root = tmp_path / "roots"
    root.mkdir()
    good = root / "g1"
    good.mkdir()
    (good / "universe.parquet").write_bytes(b"")
    monkeypatch.setenv("BACKTEST_ARCHIVE_ROOT", str(root))
    ds2 = jobs_mod._datasets_from_env()
    assert any(d["id"] == "g1" for d in ds2)


@pytest.mark.unit
def test_enforce_local_only_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKTEST_ENFORCE_LOCAL_ONLY", "0")
    q = BacktestJobQueue(auth=None)
    assert q._enforce_local_only({"x": "https://a"}) is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_jobs_finalize_records_run_backtest_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BACKTEST_ENFORCE_LOCAL_ONLY", "0")

    def boom(_opts: object) -> dict:
        raise RuntimeError("backtest boom")

    monkeypatch.setattr("bot.backtest.jobs.run_backtest", boom)

    q = BacktestJobQueue(auth=None)
    q._job_root = tmp_path / "j2"
    app = aiohttp.web.Application()
    q.register_routes(app)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{port}/api/backtest/jobs",
                json={"archive": str(tmp_path), "csrf_token": "", "fee_bps": "not-a-float"},
            ) as r:
                assert r.status == 202
                jid = (await r.json())["job_id"]
            for _ in range(80):
                await asyncio.sleep(0.05)
                async with session.get(f"http://127.0.0.1:{port}/api/backtest/jobs/{jid}") as gr:
                    st = await gr.json()
                if st.get("status") == "error":
                    assert "backtest boom" in st.get("error", "")
                    break
            else:
                raise AssertionError("job did not reach error status")
    finally:
        await runner.cleanup()