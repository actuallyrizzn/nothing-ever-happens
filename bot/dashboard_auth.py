"""Dashboard admin auth — SQLite users, bcrypt, signed session cookies, CSRF.

Admin accounts are stored only in a local SQLite file (default `dashboard_auth.sqlite`),
separate from the main bot SQLite file (`DATABASE_URL` / `NOTHING_HAPPENS_SQLITE_PATH`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import bcrypt

logger = logging.getLogger(__name__)

SESSION_COOKIE = "neh_session"
LOGIN_CSRF_COOKIE = "neh_login_csrf"
SESSION_TTL_SEC = 7 * 24 * 3600
BCRYPT_ROUNDS = 12
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


@dataclass(frozen=True)
class SessionPayload:
    user_id: int
    csrf: str
    exp: float


class DashboardAuth:
    """SQLite-backed admin users + HMAC-signed session tokens."""

    def __init__(self, secret: str, db_path: str) -> None:
        if len(secret) < 32:
            raise ValueError("DASHBOARD_AUTH_SECRET must be at least 32 characters")
        self._secret = secret.encode("utf-8")
        self._db_path = str(Path(db_path).expanduser())
        self._lock = threading.Lock()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_env(cls) -> DashboardAuth | None:
        secret = (os.getenv("DASHBOARD_AUTH_SECRET") or "").strip()
        if not secret:
            return None
        db_path = (os.getenv("DASHBOARD_AUTH_DB_PATH") or "dashboard_auth.sqlite").strip()
        auth = cls(secret, db_path)
        auth.maybe_bootstrap_from_env()
        return auth

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """
                )
                conn.commit()

    def user_count(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
                return int(row["c"]) if row else 0

    def maybe_bootstrap_from_env(self) -> None:
        """Create first user from env if DB is empty (one-shot VPS bootstrap)."""
        if self.user_count() > 0:
            return
        u = (os.getenv("DASHBOARD_BOOTSTRAP_USERNAME") or "").strip()
        p = os.getenv("DASHBOARD_BOOTSTRAP_PASSWORD") or ""
        if not u or not p:
            return
        res = self.create_user(u, p)
        if res["success"]:
            logger.info("dashboard_auth_bootstrap_user_created", extra={"username": u})
        else:
            logger.warning(
                "dashboard_auth_bootstrap_failed",
                extra={"username": u, "error": res.get("error")},
            )

    def create_user(self, username: str, password: str) -> dict[str, Any]:
        username = (username or "").strip()
        if not _USERNAME_RE.match(username):
            return {"success": False, "error": "Invalid username (1–64 chars: letters, digits, ._-)."}
        if len(password) < 8:
            return {"success": False, "error": "Password must be at least 8 characters."}
        pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode(
            "ascii"
        )
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                        (username, pw_hash),
                    )
                    conn.commit()
            except sqlite3.IntegrityError:
                return {"success": False, "error": "Username may already exist."}
        return {"success": True, "error": None}

    def verify_login(self, username: str, password: str) -> dict[str, Any]:
        username = (username or "").strip()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id, username, password_hash FROM admin_users WHERE username = ?",
                    (username,),
                ).fetchone()
        if not row or not bcrypt.checkpw(
            password.encode("utf-8"), row["password_hash"].encode("ascii")
        ):
            logger.warning("dashboard_auth_failure", extra={"username": username[:32]})
            return {"success": False, "error": "Invalid username or password."}
        return {"success": True, "user_id": int(row["id"]), "username": row["username"]}

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, username, created_at FROM admin_users ORDER BY username ASC"
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_user(self, user_id: int, current_user_id: int) -> dict[str, Any]:
        if user_id <= 0 or user_id == current_user_id:
            return {"success": False, "error": "Cannot delete this user."}
        with self._lock:
            with self._connect() as conn:
                count = int(conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0])
                if count <= 1:
                    return {"success": False, "error": "Cannot delete the last admin user."}
                cur = conn.execute("DELETE FROM admin_users WHERE id = ?", (user_id,))
                conn.commit()
                if cur.rowcount == 0:
                    return {"success": False, "error": "User not found."}
        return {"success": True, "error": None}

    def change_password(self, user_id: int, current_password: str, new_password: str) -> dict[str, Any]:
        if len(new_password) < 8:
            return {"success": False, "error": "New password must be at least 8 characters."}
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT password_hash FROM admin_users WHERE id = ?", (user_id,)
                ).fetchone()
                if not row or not bcrypt.checkpw(
                    current_password.encode("utf-8"), row["password_hash"].encode("ascii")
                ):
                    return {"success": False, "error": "Current password is incorrect."}
                pw_hash = bcrypt.hashpw(
                    new_password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
                ).decode("ascii")
                conn.execute(
                    "UPDATE admin_users SET password_hash = ? WHERE id = ?",
                    (pw_hash, user_id),
                )
                conn.commit()
        return {"success": True, "error": None}

    def sign_session(self, user_id: int) -> tuple[str, str]:
        csrf = secrets.token_hex(32)
        payload = {
            "uid": user_id,
            "csrf": csrf,
            "exp": time.time() + SESSION_TTL_SEC,
        }
        return self._sign_payload(payload), csrf

    def _sign_payload(self, data: dict[str, Any]) -> str:
        body = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        b64 = _b64url_encode(body)
        sig = hmac.new(self._secret, b64.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{b64}.{sig}"

    def read_session(self, token: str | None) -> SessionPayload | None:
        if not token:
            return None
        try:
            b64, sig = token.rsplit(".", 1)
            expect = hmac.new(self._secret, b64.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expect, sig):
                return None
            data = json.loads(_b64url_decode(b64).decode("utf-8"))
            exp = float(data.get("exp", 0))
            if time.time() > exp:
                return None
            return SessionPayload(
                user_id=int(data["uid"]),
                csrf=str(data["csrf"]),
                exp=exp,
            )
        except (ValueError, KeyError, json.JSONDecodeError, OSError):
            return None

    def verify_csrf(self, session: SessionPayload, posted: str | None) -> bool:
        if not posted:
            return False
        a, b = session.csrf, posted
        if len(a) != len(b):
            return False
        return secrets.compare_digest(a, b)


def read_cookie(request, name: str) -> str | None:
    cookies = request.cookies
    if name not in cookies:
        return None
    return cookies.get(name)


def cookie_secure(request) -> bool:
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        return True
    return request.scheme == "https"


def session_cookie_headers(
    *,
    token: str,
    request,
    max_age: int = SESSION_TTL_SEC,
) -> str:
    parts = [
        f"{SESSION_COOKIE}={token}",
        f"Max-Age={max_age}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if cookie_secure(request):
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie_header(request) -> str:
    parts = [f"{SESSION_COOKIE}=", "Max-Age=0", "Path=/", "HttpOnly", "SameSite=Lax"]
    if cookie_secure(request):
        parts.append("Secure")
    return "; ".join(parts)


def login_csrf_cookie_headers(token: str, request) -> str:
    parts = [
        f"{LOGIN_CSRF_COOKIE}={token}",
        "Max-Age=600",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if cookie_secure(request):
        parts.append("Secure")
    return "; ".join(parts)


def clear_login_csrf_cookie_header(request) -> str:
    parts = [f"{LOGIN_CSRF_COOKIE}=", "Max-Age=0", "Path=/", "HttpOnly", "SameSite=Lax"]
    if cookie_secure(request):
        parts.append("Secure")
    return "; ".join(parts)


def load_template(name: str, static_dir: Path) -> str:
    return (static_dir / name).read_text(encoding="utf-8")


def render_login_page(
    static_dir: Path,
    *,
    csrf_token: str,
    error: str = "",
    notice: str = "",
) -> str:
    html = load_template("login.html", static_dir)
    return (
        html.replace("{{CSRF_TOKEN}}", escape(csrf_token))
        .replace("{{ERROR}}", f'<p class="error">{escape(error)}</p>' if error else "")
        .replace(
            "{{NOTICE}}",
            f'<div class="info-box mb-2"><p>{escape(notice)}</p></div>' if notice else "",
        )
    )


def render_admin_users_page(
    static_dir: Path,
    *,
    csrf_token: str,
    current_user_id: int,
    users: list[dict[str, Any]],
    message: str = "",
    error: str = "",
) -> str:
    rows: list[str] = []
    for u in users:
        uid = int(u["id"])
        delete_cell = "—"
        if uid != current_user_id:
            delete_cell = (
                f'<form method="POST" style="display:inline;" '
                f'onsubmit="return confirm(\'Delete this user?\');">'
                f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
                f'<input type="hidden" name="action" value="delete">'
                f'<input type="hidden" name="id" value="{uid}">'
                f'<button type="submit" class="btn btn-secondary danger">Delete</button></form>'
            )
        you = ' <span class="muted">(you)</span>' if uid == current_user_id else ""
        rows.append(
            "<tr>"
            f"<td>{escape(str(u['username']))}{you}</td>"
            f"<td>{escape(str(u.get('created_at', '')))}</td>"
            f"<td>{delete_cell}</td>"
            "</tr>"
        )
    tbody = "\n".join(rows) if rows else '<tr><td colspan="3" class="muted">No users</td></tr>'
    html = load_template("admin_users.html", static_dir)
    return (
        html.replace("{{CSRF_TOKEN}}", escape(csrf_token))
        .replace("{{USERS_ROWS}}", tbody)
        .replace("{{MESSAGE}}", f'<div class="info-box mb-2"><p>{escape(message)}</p></div>' if message else "")
        .replace("{{ERROR}}", f'<p class="error">{escape(error)}</p>' if error else "")
    )


def render_change_password_page(
    static_dir: Path,
    *,
    csrf_token: str,
    message: str = "",
    error: str = "",
) -> str:
    html = load_template("change_password.html", static_dir)
    return (
        html.replace("{{CSRF_TOKEN}}", escape(csrf_token))
        .replace("{{MESSAGE}}", f'<div class="info-box mb-2"><p>{escape(message)}</p></div>' if message else "")
        .replace("{{ERROR}}", f'<p class="error">{escape(error)}</p>' if error else "")
    )


def render_admin_settings_page(
    static_dir: Path,
    *,
    csrf_token: str,
    form_fields_html: str,
    restart_request_block: str = "",
    paper_wallet_block: str = "",
    backtest_nav_link: str = "",
    backtest_disabled_hint: str = "",
    message: str = "",
    error: str = "",
) -> str:
    html = load_template("admin_settings.html", static_dir)
    return (
        html.replace("{{CSRF_TOKEN}}", escape(csrf_token))
        .replace("{{FORM_FIELDS}}", form_fields_html)
        .replace("{{RESTART_REQUEST_BLOCK}}", restart_request_block)
        .replace("{{PAPER_WALLET_BLOCK}}", paper_wallet_block)
        .replace("{{BACKTEST_NAV_LINK}}", backtest_nav_link)
        .replace("{{BACKTEST_DISABLED_HINT}}", backtest_disabled_hint)
        .replace("{{MESSAGE}}", f'<div class="info-box mb-2"><p>{escape(message)}</p></div>' if message else "")
        .replace("{{ERROR}}", f'<p class="error">{escape(error)}</p>' if error else "")
    )
