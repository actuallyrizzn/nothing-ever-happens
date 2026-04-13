"""Dashboard web server via aiohttp + WebSocket."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from collections import deque
from html import escape as html_escape
from pathlib import Path

from aiohttp import web
from multidict import MultiDict

from bot.dashboard_auth import (
    LOGIN_CSRF_COOKIE,
    SESSION_COOKIE,
    DashboardAuth,
    clear_login_csrf_cookie_header,
    clear_session_cookie_header,
    login_csrf_cookie_headers,
    read_cookie,
    render_admin_users_page,
    render_change_password_page,
    render_login_page,
    session_cookie_headers,
)
from bot.nothing_happens_control import NothingHappensControlState

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

_AUTH_DEFAULT = object()


def _csrf_tokens_equal(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


BACKGROUND_IMAGE = STATIC_DIR / "nothingeverhappens.svg"
BALANCE_POLL_INTERVAL_SEC = 30.0
BALANCE_TIMEOUT_SEC = 10.0
RESOLUTION_POLL_INTERVAL_SEC = 15.0
TRADE_HISTORY_LIMIT = 1000
BALANCE_HISTORY_LIMIT = 2880


class DashboardServer:
    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        exchange=None,
        portfolio_state=None,
        nothing_happens_control: NothingHappensControlState | None = None,
        auth: DashboardAuth | None | object = _AUTH_DEFAULT,
    ):
        self.host = host
        self.port = port
        self._exchange = exchange
        self._portfolio_state = portfolio_state
        self._nothing_happens_control = nothing_happens_control
        if auth is _AUTH_DEFAULT:
            self._auth = DashboardAuth.from_env()
        else:
            self._auth = auth  # type: ignore[assignment]
        self._clients: set[web.WebSocketResponse] = set()
        self._last_portfolio_version = -1
        self._last_nothing_happens_control_version = -1
        self._ledger_path = os.getenv("TRADE_LEDGER_PATH", "trades.jsonl")
        self._ledger_pos = 0
        self._trade_history: deque[dict] = deque(maxlen=TRADE_HISTORY_LIMIT)
        self._starting_balance: float | None = None
        self._current_balance: float | None = None
        self._last_balance_poll = 0.0
        self._balance_history: deque[tuple[float, float]] = deque(maxlen=BALANCE_HISTORY_LIMIT)
        self._resolutions: dict[str, str] = {}
        self._pending_resolution_slugs: list[str] = []
        self._last_resolution_poll = 0.0

    async def _index(self, request: web.Request):
        if self._auth is None:
            return web.FileResponse(STATIC_DIR / "dashboard.html")
        csrf = str(request.get("dashboard_csrf", ""))
        html = (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
        bar = (
            '<div id="neh-admin-nav" style="position:fixed;top:12px;right:16px;z-index:10000;'
            'display:flex;gap:10px;align-items:center;font-family:system-ui,sans-serif;font-size:13px;">'
            '<a href="/admin/users" style="color:#e79d54;text-decoration:none;">Admin</a>'
            '<a href="/admin/change-password" style="color:#b2a796;text-decoration:none;">Password</a>'
            '<form method="POST" action="/logout" style="margin:0;display:inline;">'
            f'<input type="hidden" name="csrf_token" value="{html_escape(csrf)}">'
            '<button type="submit" style="background:transparent;border:1px solid rgba(255,234,205,0.2);'
            'color:#b2a796;border-radius:6px;padding:4px 10px;cursor:pointer;">Logout</button>'
            "</form></div>"
        )
        if "</body>" in html:
            html = html.replace("</body>", bar + "\n</body>", 1)
        else:
            html += bar
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _background_image(self, request: web.Request):
        if not BACKGROUND_IMAGE.exists():
            raise web.HTTPNotFound(text="background image not found")
        return web.FileResponse(BACKGROUND_IMAGE)

    async def _login_get(self, request: web.Request):
        if self._auth is None:
            raise web.HTTPNotFound()
        existing = self._auth.read_session(read_cookie(request, SESSION_COOKIE))
        if existing is not None:
            raise web.HTTPFound(location="/")
        login_csrf = os.urandom(32).hex()
        notice = ""
        if self._auth.user_count() == 0:
            notice = (
                "No admin users yet. Set DASHBOARD_BOOTSTRAP_USERNAME and "
                "DASHBOARD_BOOTSTRAP_PASSWORD and restart, or run "
                "python scripts/dashboard_create_user.py"
            )
        body = render_login_page(STATIC_DIR, csrf_token=login_csrf, notice=notice)
        resp = web.Response(text=body, content_type="text/html", charset="utf-8")
        resp.headers["Set-Cookie"] = login_csrf_cookie_headers(login_csrf, request)
        return resp

    async def _login_post(self, request: web.Request):
        if self._auth is None:
            raise web.HTTPNotFound()
        data = await request.post()
        posted = data.get("csrf_token")
        cookie_tok = read_cookie(request, LOGIN_CSRF_COOKIE)
        if not posted or not cookie_tok or not _csrf_tokens_equal(str(posted), cookie_tok):
            body = render_login_page(
                STATIC_DIR,
                csrf_token=os.urandom(32).hex(),
                error="Invalid security token. Refresh the page and try again.",
            )
            resp = web.Response(text=body, content_type="text/html", charset="utf-8", status=403)
            resp.headers["Set-Cookie"] = login_csrf_cookie_headers(os.urandom(32).hex(), request)
            return resp
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        result = self._auth.verify_login(username, password)
        if not result["success"]:
            new_csrf = os.urandom(32).hex()
            body = render_login_page(STATIC_DIR, csrf_token=new_csrf, error=result["error"])
            resp = web.Response(text=body, content_type="text/html", charset="utf-8")
            resp.headers["Set-Cookie"] = login_csrf_cookie_headers(new_csrf, request)
            return resp
        session_token, _csrf = self._auth.sign_session(int(result["user_id"]))
        hdr = MultiDict()
        hdr.add("Set-Cookie", session_cookie_headers(token=session_token, request=request))
        hdr.add("Set-Cookie", clear_login_csrf_cookie_header(request))
        raise web.HTTPFound(location="/", headers=hdr)

    async def _logout_post(self, request: web.Request):
        if self._auth is None:
            raise web.HTTPNotFound()
        data = await request.post()
        uid = int(request["dashboard_uid"])
        sess = self._auth.read_session(read_cookie(request, SESSION_COOKIE))
        if sess is None or sess.user_id != uid:
            raise web.HTTPFound(location="/login")
        if not self._auth.verify_csrf(sess, str(data.get("csrf_token") or "")):
            return web.Response(status=403, text="CSRF validation failed")
        hdr = MultiDict()
        hdr.add("Set-Cookie", clear_session_cookie_header(request))
        raise web.HTTPFound(location="/login", headers=hdr)

    async def _admin_users_get(self, request: web.Request):
        if self._auth is None:
            raise web.HTTPNotFound()
        uid = int(request["dashboard_uid"])
        csrf = str(request["dashboard_csrf"])
        users = self._auth.list_users()
        body = render_admin_users_page(
            STATIC_DIR,
            csrf_token=csrf,
            current_user_id=uid,
            users=users,
        )
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    async def _admin_users_post(self, request: web.Request):
        if self._auth is None:
            raise web.HTTPNotFound()
        data = await request.post()
        uid = int(request["dashboard_uid"])
        sess = self._auth.read_session(read_cookie(request, SESSION_COOKIE))
        if sess is None or sess.user_id != uid:
            return web.Response(status=403, text="Session invalid")
        if not self._auth.verify_csrf(sess, str(data.get("csrf_token") or "")):
            return web.Response(status=403, text="CSRF validation failed")
        action = data.get("action")
        message = ""
        error = ""
        if action == "create":
            res = self._auth.create_user(data.get("username") or "", data.get("password") or "")
            if res["success"]:
                message = "User created."
            else:
                error = res["error"]
        elif action == "delete":
            res = self._auth.delete_user(int(data.get("id") or 0), uid)
            if res["success"]:
                message = "User deleted."
            else:
                error = res["error"]
        else:
            error = "Unknown action."
        users = self._auth.list_users()
        body = render_admin_users_page(
            STATIC_DIR,
            csrf_token=sess.csrf,
            current_user_id=uid,
            users=users,
            message=message,
            error=error,
        )
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    async def _change_password_get(self, request: web.Request):
        if self._auth is None:
            raise web.HTTPNotFound()
        csrf = str(request["dashboard_csrf"])
        body = render_change_password_page(STATIC_DIR, csrf_token=csrf)
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    async def _change_password_post(self, request: web.Request):
        if self._auth is None:
            raise web.HTTPNotFound()
        data = await request.post()
        uid = int(request["dashboard_uid"])
        sess = self._auth.read_session(read_cookie(request, SESSION_COOKIE))
        if sess is None or sess.user_id != uid:
            return web.Response(status=403, text="Session invalid")
        if not self._auth.verify_csrf(sess, str(data.get("csrf_token") or "")):
            return web.Response(status=403, text="CSRF validation failed")
        new_pw = data.get("new_password") or ""
        if new_pw != (data.get("new_password_confirm") or ""):
            body = render_change_password_page(
                STATIC_DIR, csrf_token=sess.csrf, error="New passwords do not match."
            )
            return web.Response(text=body, content_type="text/html", charset="utf-8")
        res = self._auth.change_password(
            uid, data.get("current_password") or "", new_pw
        )
        if res["success"]:
            body = render_change_password_page(
                STATIC_DIR, csrf_token=sess.csrf, message="Password updated."
            )
        else:
            body = render_change_password_page(
                STATIC_DIR, csrf_token=sess.csrf, error=res["error"]
            )
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    async def _ws_handler(self, request: web.Request):
        if self._auth is not None:
            sess = self._auth.read_session(read_cookie(request, SESSION_COOKIE))
            if sess is None:
                raise web.HTTPUnauthorized()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("Dashboard client connected (%d total)", len(self._clients))
        await self._send_initial(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(ws, msg.data)
        finally:
            self._clients.discard(ws)
            logger.info("Dashboard client disconnected (%d remaining)", len(self._clients))
        return ws

    async def _handle_ws_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_to(ws, {"type": "control_ack", "ok": False, "error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            await self._send_to(ws, {"type": "control_ack", "ok": False, "error": "invalid_payload"})
            return
        if payload.get("type") == "set_position_target":
            await self._send_to(ws, {"type": "control_ack", "ok": False, "error": "controls_disabled"})

    async def _send_to(self, ws: web.WebSocketResponse, data: dict) -> None:
        try:
            await ws.send_str(json.dumps(data))
        except Exception:
            self._clients.discard(ws)

    async def _broadcast(self, data: dict) -> None:
        if not self._clients:
            return
        message = json.dumps(data)
        dead: set[web.WebSocketResponse] = set()
        for ws in self._clients:
            try:
                await ws.send_str(message)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _send_initial(self, ws: web.WebSocketResponse) -> None:
        portfolio_message = self._make_portfolio_message(force=True)
        if portfolio_message is not None:
            await self._send_to(ws, portfolio_message)
        if self._starting_balance is not None and self._current_balance is not None:
            await self._send_to(ws, self._make_pnl_message())
        if self._balance_history:
            await self._send_to(
                ws,
                {
                    "type": "balance_history",
                    "points": [
                        {"ts": ts * 1000, "balance": round(balance, 2)}
                        for ts, balance in self._balance_history
                    ],
                },
            )
        for trade in list(self._trade_history)[-500:]:
            await self._send_to(ws, trade)
        for slug, winner in self._resolutions.items():
            await self._send_to(
                ws,
                {"type": "resolution", "market_slug": slug, "winner": winner},
            )

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Dashboard poll error: %s", exc)
            await asyncio.sleep(0.25)

    async def _poll_once(self) -> None:
        portfolio_message = self._make_portfolio_message()
        if portfolio_message is not None:
            await self._broadcast(portfolio_message)
        await self._poll_trades()
        await self._poll_balance()
        await self._poll_resolutions()

    def _make_portfolio_message(self, *, force: bool = False) -> dict | None:
        if self._portfolio_state is None:
            return None
        version = self._portfolio_state.version()
        control_version = (
            self._nothing_happens_control.version()
            if self._nothing_happens_control is not None
            else -1
        )
        if (
            not force
            and version == self._last_portfolio_version
            and control_version == self._last_nothing_happens_control_version
        ):
            return None
        self._last_portfolio_version = version
        self._last_nothing_happens_control_version = control_version
        snapshot = self._portfolio_state.snapshot()
        control_snapshot = (
            self._nothing_happens_control.snapshot()
            if self._nothing_happens_control is not None
            else None
        )
        return {
            "type": "portfolio",
            "updated_at_us": snapshot.updated_at_us,
            "monitored_markets": snapshot.monitored_markets,
            "eligible_markets": snapshot.eligible_markets,
            "in_range_markets": snapshot.in_range_markets,
            "cash_balance": snapshot.cash_balance,
            "last_market_refresh_ts": snapshot.last_market_refresh_ts,
            "last_position_sync_ts": snapshot.last_position_sync_ts,
            "last_price_cycle_ts": snapshot.last_price_cycle_ts,
            "last_error": snapshot.last_error,
            "target_open_positions": (
                control_snapshot.target_open_positions if control_snapshot is not None else None
            ),
            "pending_entry_count": (
                control_snapshot.pending_entry_count if control_snapshot is not None else 0
            ),
            "remaining_position_capacity": (
                control_snapshot.remaining_capacity if control_snapshot is not None else None
            ),
            "opened_this_run": (
                control_snapshot.opened_this_run if control_snapshot is not None else 0
            ),
            "controls_enabled": control_snapshot is not None,
            "positions": [
                {
                    "slug": position.slug,
                    "title": position.title,
                    "outcome": position.outcome,
                    "asset": position.asset,
                    "condition_id": position.condition_id,
                    "size": round(position.size, 6),
                    "avg_price": round(position.avg_price, 6),
                    "initial_value": round(position.initial_value, 6),
                    "current_price": round(position.current_price, 6),
                    "current_value": round(position.current_value, 6),
                    "pnl_usd": round(position.pnl_usd, 6),
                    "pnl_pct": round(position.pnl_pct, 6),
                    "end_date": position.end_date,
                    "eta_seconds": round(position.eta_seconds, 3),
                    "source": position.source,
                }
                for position in snapshot.positions
            ],
        }

    async def _poll_trades(self) -> None:
        try:
            if not os.path.exists(self._ledger_path):
                return
            with open(self._ledger_path, "r") as f:
                f.seek(self._ledger_pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    trade_msg = {"type": "bot_trade", **record}
                    self._trade_history.append(trade_msg)
                    await self._broadcast(trade_msg)
                self._ledger_pos = f.tell()
        except Exception as exc:
            logger.debug("Trade ledger poll error: %s", exc)

    def _make_pnl_message(self) -> dict:
        pnl_usd = (self._current_balance or 0.0) - (self._starting_balance or 0.0)
        pnl_pct = (
            (pnl_usd / self._starting_balance * 100.0)
            if self._starting_balance and self._starting_balance > 0
            else 0.0
        )
        return {
            "type": "session_pnl",
            "starting_balance": round(self._starting_balance or 0.0, 2),
            "current_balance": round(self._current_balance or 0.0, 2),
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct, 2),
        }

    async def _poll_balance(self) -> None:
        if self._exchange is None:
            return
        loop_now = asyncio.get_running_loop().time()
        if loop_now - self._last_balance_poll < BALANCE_POLL_INTERVAL_SEC:
            return
        self._last_balance_poll = loop_now
        try:
            balance = await asyncio.wait_for(
                asyncio.to_thread(self._exchange.get_collateral_balance),
                timeout=BALANCE_TIMEOUT_SEC,
            )
            if self._starting_balance is None:
                self._starting_balance = balance
                logger.info(
                    "dashboard_starting_balance",
                    extra={"balance": round(balance, 2)},
                )
            self._current_balance = balance
            ts_sec = time.time()
            self._balance_history.append((ts_sec, balance))
            await self._broadcast(self._make_pnl_message())
            await self._broadcast(
                {
                    "type": "balance_point",
                    "ts": ts_sec * 1000,
                    "balance": round(balance, 2),
                }
            )
        except Exception as exc:
            logger.debug("Dashboard balance poll failed: %s", exc)

    async def _poll_resolutions(self) -> None:
        loop_now = asyncio.get_running_loop().time()
        if loop_now - self._last_resolution_poll < RESOLUTION_POLL_INTERVAL_SEC:
            return
        self._last_resolution_poll = loop_now

        for trade in self._trade_history:
            slug = trade.get("market_slug", "")
            if slug and slug not in self._resolutions and slug not in self._pending_resolution_slugs:
                self._pending_resolution_slugs.append(slug)

        if not self._pending_resolution_slugs:
            return

        from bot.live_recovery import _check_gamma_resolution

        for slug in self._pending_resolution_slugs[:5]:
            try:
                winner = await _check_gamma_resolution(slug)
                if winner is None:
                    continue
                display_winner = winner.capitalize()
                self._resolutions[slug] = display_winner
                self._pending_resolution_slugs.remove(slug)
                await self._broadcast(
                    {
                        "type": "resolution",
                        "market_slug": slug,
                        "winner": display_winner,
                    }
                )
                logger.info("Resolution: %s -> %s", slug, display_winner)
            except Exception as exc:
                logger.debug("Resolution fetch failed for %s: %s", slug, exc)

    def build_app(self) -> web.Application:
        @web.middleware
        async def auth_middleware(request: web.Request, handler):
            if self._auth is None:
                return await handler(request)
            path = request.path
            if path == "/login" and request.method in ("GET", "HEAD", "POST"):
                return await handler(request)
            token = read_cookie(request, SESSION_COOKIE)
            sess = self._auth.read_session(token)
            if sess is None:
                if path == "/ws":
                    return web.Response(status=401, text="Authentication required")
                accept = request.headers.get("Accept", "")
                if request.method == "GET" and "text/html" in accept:
                    raise web.HTTPFound(location="/login")
                return web.Response(status=401, text="Authentication required")
            request["dashboard_uid"] = sess.user_id
            request["dashboard_csrf"] = sess.csrf
            return await handler(request)

        middlewares = [auth_middleware] if self._auth else []
        app = web.Application(middlewares=middlewares)
        app.router.add_get("/", self._index)
        app.router.add_get("/nothingeverhappens.svg", self._background_image)
        app.router.add_get("/ws", self._ws_handler)
        if self._auth:
            app.router.add_get("/login", self._login_get)
            app.router.add_post("/login", self._login_post)
            app.router.add_post("/logout", self._logout_post)
            app.router.add_get("/admin/users", self._admin_users_get)
            app.router.add_post("/admin/users", self._admin_users_post)
            app.router.add_get("/admin/change-password", self._change_password_get)
            app.router.add_post("/admin/change-password", self._change_password_post)
        return app

    async def run(self) -> None:
        app = self.build_app()

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(
            "Dashboard at http://%s:%d (auth=%s)",
            self.host,
            self.port,
            "on" if self._auth else "off",
        )

        try:
            await self._poll_loop()
        finally:
            await runner.cleanup()
