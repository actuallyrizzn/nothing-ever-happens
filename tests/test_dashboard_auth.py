"""Dashboard authentication (session, login, CSRF)."""

from __future__ import annotations

import re

import aiohttp
import pytest

from bot.dashboard import DashboardServer
from bot.dashboard_auth import SESSION_COOKIE, DashboardAuth
from bot.portfolio_state import PortfolioState


def _make_portfolio_state() -> PortfolioState:
    portfolio_state = PortfolioState()
    portfolio_state.update(
        updated_at_us=1,
        monitored_markets=12,
        eligible_markets=10,
        in_range_markets=3,
        positions=[],
        cash_balance=42.0,
        last_market_refresh_ts=1.0,
        last_position_sync_ts=1.0,
        last_price_cycle_ts=1.0,
        last_error="",
    )
    return portfolio_state


@pytest.fixture
def auth_secret() -> str:
    return "z" * 32


@pytest.fixture
def auth_db_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'neh_admin.db'}"


def test_dashboard_auth_sign_roundtrip(auth_secret: str, auth_db_url: str):
    auth = DashboardAuth(auth_secret, auth_db_url)
    token, _ = auth.sign_session(42)
    sess = auth.read_session(token)
    assert sess is not None
    assert sess.user_id == 42
    assert len(sess.csrf) == 64


def test_dashboard_auth_create_user(auth_secret: str, auth_db_url: str):
    auth = DashboardAuth(auth_secret, auth_db_url)
    assert auth.create_user("ok_user", "password123")["success"] is True
    assert auth.verify_login("ok_user", "password123")["success"] is True
    assert auth.verify_login("ok_user", "wrong")["success"] is False


@pytest.mark.asyncio
async def test_auth_redirects_root_to_login(auth_secret: str, auth_db_url: str):
    auth = DashboardAuth(auth_secret, auth_db_url)
    auth.create_user("alice", "password123")
    server = DashboardServer(port=0, portfolio_state=_make_portfolio_state(), auth=auth)
    app = server.build_app()
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}/",
                headers={"Accept": "text/html"},
                allow_redirects=False,
            ) as resp:
                assert resp.status == 302
                assert resp.headers.get("Location") == "/login"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_auth_login_and_access_dashboard(auth_secret: str, auth_db_url: str):
    auth = DashboardAuth(auth_secret, auth_db_url)
    auth.create_user("alice", "password123")
    server = DashboardServer(port=0, portfolio_state=_make_portfolio_state(), auth=auth)
    app = server.build_app()
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar) as session:
            async with session.get(f"http://127.0.0.1:{port}/login") as login_page:
                assert login_page.status == 200
                html = await login_page.text()
            m = re.search(r'name="csrf_token" value="([^"]+)"', html)
            assert m is not None
            csrf = m.group(1)
            async with session.post(
                f"http://127.0.0.1:{port}/login",
                data={
                    "username": "alice",
                    "password": "password123",
                    "csrf_token": csrf,
                },
                allow_redirects=False,
            ) as post_login:
                assert post_login.status == 302
                assert post_login.headers.get("Location") == "/"
            assert any(c.key == SESSION_COOKIE for c in jar)
            async with session.get(
                f"http://127.0.0.1:{port}/",
                headers={"Accept": "text/html"},
            ) as dash:
                assert dash.status == 200
                body = await dash.text()
                assert "Open Positions" in body or "Dashboard" in body
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_auth_websocket_rejects_without_session(auth_secret: str, auth_db_url: str):
    auth = DashboardAuth(auth_secret, auth_db_url)
    auth.create_user("alice", "password123")
    server = DashboardServer(port=0, portfolio_state=_make_portfolio_state(), auth=auth)
    app = server.build_app()
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientResponseError) as exc_info:
                async with session.ws_connect(f"http://127.0.0.1:{port}/ws"):
                    pass
            assert exc_info.value.status == 401
    finally:
        await runner.cleanup()
