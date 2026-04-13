"""Runtime configuration stored in SQLite and edited from the dashboard.

Rows in ``runtime_settings`` are applied into ``os.environ`` once at process
startup (after ``init_db``), before ``load_nothing_happens_config()``. That lets
the existing config stack (env vars + config.json fallbacks) keep working while
DB values override when present.

Secrets (private key, RPC URL, funder) live in the DB like other values; protect
the SQLite file permissions and backups accordingly. Changing settings from the
dashboard updates the DB immediately but **does not** rebuild the live exchange
client — **restart the bot process** to apply trading connection and strategy
tuning to the running engine.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from bot.db import runtime_settings_table

logger = logging.getLogger(__name__)

_SECRET_SENTINEL = "(unchanged)"


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    section: str
    kind: str  # str | int | float | bool | choice
    help: str = ""
    secret: bool = False
    choices: tuple[str, ...] = ()
    # Second line under the control: units and scale (not basis points unless stated).
    value_hint: str = ""


# All keys we support in the admin UI / DB (non-secret defaults can be seeded).
FIELDS: tuple[SettingField, ...] = (
    SettingField(
        "BOT_MODE",
        "Bot mode",
        "Trading mode",
        "choice",
        "paper = simulated exchange; live = real CLOB when safety toggles allow.",
        choices=("paper", "live"),
    ),
    SettingField(
        "DRY_RUN",
        "Dry run",
        "Trading mode",
        "bool",
        "If true, live order sends are blocked.",
    ),
    SettingField(
        "LIVE_TRADING_ENABLED",
        "Live trading enabled",
        "Trading mode",
        "bool",
        "Real orders only when this is on, mode is live, and dry run is off.",
    ),
    SettingField(
        "PRIVATE_KEY",
        "Private key",
        "Secrets",
        "str",
        "Hex key for CLOB signing. Leave blank when saving to keep the stored key.",
        secret=True,
    ),
    SettingField(
        "FUNDER_ADDRESS",
        "Funder / proxy address",
        "Secrets",
        "str",
        "0x address; required for signature types 1 and 2. Leave blank when saving to keep stored.",
        secret=True,
    ),
    SettingField(
        "POLYGON_RPC_URL",
        "Polygon RPC URL",
        "Secrets",
        "str",
        "HTTPS JSON-RPC for on-chain steps. Leave blank when saving to keep stored.",
        secret=True,
    ),
    SettingField(
        "PM_CONNECTION_HOST",
        "CLOB host",
        "Polymarket connection",
        "str",
        "CLOB API base URL (default https://clob.polymarket.com).",
    ),
    SettingField(
        "PM_CONNECTION_CHAIN_ID",
        "Chain ID",
        "Polymarket connection",
        "int",
        "Chain id (Polygon mainnet is usually 137).",
    ),
    SettingField(
        "PM_CONNECTION_SIGNATURE_TYPE",
        "Signature type",
        "Polymarket connection",
        "choice",
        "0 = EOA; 1 / 2 = proxy or delegated wallet.",
        choices=("0", "1", "2"),
    ),
    SettingField(
        "TRADE_LEDGER_PATH",
        "Trade ledger (JSONL)",
        "Paths & logging",
        "str",
        "Append-only JSONL file path (create parent directories if needed).",
    ),
    SettingField(
        "LOG_LEVEL",
        "Log level",
        "Paths & logging",
        "choice",
        "DEBUG is very verbose.",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    ),
    SettingField(
        "PM_BACKGROUND_EXECUTOR_WORKERS",
        "Background executor workers",
        "Paths & logging",
        "int",
        "Thread pool size for blocking API calls (minimum 1).",
    ),
    SettingField(
        "BOT_VARIANT",
        "Bot variant tag",
        "Paths & logging",
        "str",
        "Optional short label on ledger rows; can be empty.",
    ),
    SettingField(
        "PM_NH_MAX_END_DATE_MONTHS",
        "Max end date (months)",
        "Strategy",
        "int",
        "Ignore markets ending more than this many months ahead (30-day months).",
    ),
    SettingField(
        "PM_NH_MIN_RESOLUTION_ETA_SEC",
        "Min resolution ETA (sec)",
        "Strategy",
        "int",
        "Skip markets resolving sooner than this many seconds from now; 0 = no minimum.",
    ),
    SettingField(
        "PM_NH_MAX_RESOLUTION_ETA_SEC",
        "Max resolution ETA (sec)",
        "Strategy",
        "int",
        "Skip markets resolving later than this many seconds from now; 0 = no maximum.",
    ),
    SettingField(
        "PM_NH_MARKET_REFRESH_INTERVAL_SEC",
        "Market refresh (sec)",
        "Strategy",
        "int",
        "Seconds between candidate-market list refreshes.",
    ),
    SettingField(
        "PM_NH_PRICE_POLL_INTERVAL_SEC",
        "Price poll (sec)",
        "Strategy",
        "int",
        "Seconds between price polls on tracked markets.",
    ),
    SettingField(
        "PM_NH_POSITION_SYNC_INTERVAL_SEC",
        "Position sync (sec)",
        "Strategy",
        "int",
        "Seconds between position and cash sync with the exchange.",
    ),
    SettingField(
        "PM_NH_ORDER_DISPATCH_INTERVAL_SEC",
        "Order dispatch (sec)",
        "Strategy",
        "int",
        "Seconds between attempts to open new positions.",
    ),
    SettingField(
        "PM_NH_CASH_PCT_PER_TRADE",
        "Cash % per trade",
        "Strategy",
        "float",
        "Fraction of cash per trade as a decimal 0–1 (0.02 = 2%, not 2).",
    ),
    SettingField(
        "PM_NH_MIN_TRADE_AMOUNT",
        "Min trade amount (USD)",
        "Strategy",
        "float",
        "Minimum order notional in USD.",
    ),
    SettingField(
        "PM_NH_FIXED_TRADE_AMOUNT_USD",
        "Fixed trade amount (USD)",
        "Strategy",
        "float",
        "Fixed USD per trade; 0 uses only the cash % setting.",
    ),
    SettingField(
        "PM_NH_MAX_ENTRY_PRICE",
        "Max entry price",
        "Strategy",
        "float",
        "NO price cap on Polymarket’s 0–1 scale (e.g. 0.65), not cents or bps.",
    ),
    SettingField(
        "PM_NH_ALLOWED_SLIPPAGE",
        "Allowed slippage",
        "Strategy",
        "float",
        "Slippage headroom on the same 0–1 scale as max entry.",
    ),
    SettingField(
        "PM_NH_REQUEST_CONCURRENCY",
        "Request concurrency",
        "Strategy",
        "int",
        "Parallel in-flight exchange requests.",
    ),
    SettingField(
        "PM_NH_BUY_RETRY_COUNT",
        "Buy retry count",
        "Strategy",
        "int",
        "Retries after a failed buy before giving up.",
    ),
    SettingField(
        "PM_NH_BUY_RETRY_BASE_DELAY_SEC",
        "Buy retry base delay (sec)",
        "Strategy",
        "float",
        "First retry backoff in seconds (decimals allowed).",
    ),
    SettingField(
        "PM_NH_MAX_BACKOFF_SEC",
        "Max backoff (sec)",
        "Strategy",
        "float",
        "Maximum delay between retries.",
    ),
    SettingField(
        "PM_NH_MAX_NEW_POSITIONS",
        "Max new positions",
        "Strategy",
        "int",
        "Max new positions per run; -1 = unlimited.",
    ),
    SettingField(
        "PM_NH_SHUTDOWN_ON_MAX_NEW_POSITIONS",
        "Shutdown on max positions",
        "Strategy",
        "bool",
        "Stop opening new positions once the cap is reached.",
    ),
    SettingField(
        "PM_NH_REDEEMER_INTERVAL_SEC",
        "Redeemer interval (sec)",
        "Strategy",
        "int",
        "Seconds between on-chain redeem passes when redemption runs.",
    ),
    SettingField(
        "PM_RISK_MAX_TOTAL_OPEN_EXPOSURE_USD",
        "Max total open exposure (USD)",
        "Risk",
        "float",
        "Total open notional cap across markets; 0 = built-in default.",
    ),
    SettingField(
        "PM_RISK_MAX_MARKET_OPEN_EXPOSURE_USD",
        "Max per-market exposure (USD)",
        "Risk",
        "float",
        "Open notional cap for one market.",
    ),
    SettingField(
        "PM_RISK_MAX_DAILY_DRAWDOWN_USD",
        "Max daily drawdown (USD)",
        "Risk",
        "float",
        "Drop from the day’s balance high that trips the breaker; 0 = off.",
    ),
    SettingField(
        "PM_RISK_KILL_COOLDOWN_SEC",
        "Kill-switch cooldown (sec)",
        "Risk",
        "float",
        "Wait time after a risk kill before new entries.",
    ),
    SettingField(
        "PM_RISK_DRAWDOWN_ARM_AFTER_SEC",
        "Drawdown arm after (sec)",
        "Risk",
        "float",
        "Startup grace period before drawdown rules apply.",
    ),
    SettingField(
        "PM_RISK_DRAWDOWN_MIN_FRESH_OBS",
        "Drawdown min fresh observations",
        "Risk",
        "int",
        "Balance readings required before drawdown logic runs.",
    ),
)

FIELD_BY_KEY = {f.key: f for f in FIELDS}


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _defaults_from_config_json(cfg: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    conn = cfg.get("connection")
    if isinstance(conn, dict):
        if conn.get("host") is not None:
            out["PM_CONNECTION_HOST"] = str(conn["host"])
        if conn.get("chain_id") is not None:
            out["PM_CONNECTION_CHAIN_ID"] = str(int(conn["chain_id"]))
        if conn.get("signature_type") is not None:
            out["PM_CONNECTION_SIGNATURE_TYPE"] = str(int(conn["signature_type"]))
    strat = (cfg.get("strategies") or {}).get("nothing_happens")
    if not isinstance(strat, dict):
        return out

    def i(name: str, k: str) -> None:
        if strat.get(k) is not None:
            out[name] = str(int(strat[k]))

    def f(name: str, k: str) -> None:
        if strat.get(k) is not None:
            out[name] = str(float(strat[k]))

    i("PM_NH_MAX_END_DATE_MONTHS", "max_end_date_months")
    i("PM_NH_MIN_RESOLUTION_ETA_SEC", "min_resolution_eta_sec")
    i("PM_NH_MAX_RESOLUTION_ETA_SEC", "max_resolution_eta_sec")
    i("PM_NH_MARKET_REFRESH_INTERVAL_SEC", "market_refresh_interval_sec")
    i("PM_NH_PRICE_POLL_INTERVAL_SEC", "price_poll_interval_sec")
    i("PM_NH_POSITION_SYNC_INTERVAL_SEC", "position_sync_interval_sec")
    i("PM_NH_ORDER_DISPATCH_INTERVAL_SEC", "order_dispatch_interval_sec")
    f("PM_NH_CASH_PCT_PER_TRADE", "cash_pct_per_trade")
    f("PM_NH_MIN_TRADE_AMOUNT", "min_trade_amount")
    f("PM_NH_FIXED_TRADE_AMOUNT_USD", "fixed_trade_amount")
    f("PM_NH_MAX_ENTRY_PRICE", "max_entry_price")
    f("PM_NH_ALLOWED_SLIPPAGE", "allowed_slippage")
    i("PM_NH_REQUEST_CONCURRENCY", "request_concurrency")
    i("PM_NH_BUY_RETRY_COUNT", "buy_retry_count")
    f("PM_NH_BUY_RETRY_BASE_DELAY_SEC", "buy_retry_base_delay_sec")
    f("PM_NH_MAX_BACKOFF_SEC", "max_backoff_sec")
    i("PM_NH_MAX_NEW_POSITIONS", "max_new_positions")
    if strat.get("shutdown_on_max_new_positions") is not None:
        v = strat["shutdown_on_max_new_positions"]
        out["PM_NH_SHUTDOWN_ON_MAX_NEW_POSITIONS"] = "true" if v else "false"
    i("PM_NH_REDEEMER_INTERVAL_SEC", "redeemer_interval_sec")
    return out


def _builtin_seed_defaults() -> dict[str, str]:
    """Match config.example.json + .env.example for non-secret keys."""
    path = Path(__file__).resolve().parent.parent / "config.example.json"
    if path.exists():
        with path.open(encoding="utf-8") as fp:
            cfg = json.load(fp)
        base = _defaults_from_config_json(cfg)
    else:
        base = {}
    base.setdefault("BOT_MODE", "paper")
    base.setdefault("DRY_RUN", "true")
    base.setdefault("LIVE_TRADING_ENABLED", "false")
    base.setdefault("TRADE_LEDGER_PATH", "trades.jsonl")
    base.setdefault("LOG_LEVEL", "INFO")
    base.setdefault("PM_BACKGROUND_EXECUTOR_WORKERS", "8")
    base.setdefault("PM_CONNECTION_HOST", "https://clob.polymarket.com")
    base.setdefault("PM_CONNECTION_CHAIN_ID", "137")
    base.setdefault("PM_CONNECTION_SIGNATURE_TYPE", "2")
    base.setdefault("PM_RISK_MAX_TOTAL_OPEN_EXPOSURE_USD", "1500")
    base.setdefault("PM_RISK_MAX_MARKET_OPEN_EXPOSURE_USD", "1000")
    base.setdefault("PM_RISK_MAX_DAILY_DRAWDOWN_USD", "0")
    base.setdefault("PM_RISK_KILL_COOLDOWN_SEC", "900")
    base.setdefault("PM_RISK_DRAWDOWN_ARM_AFTER_SEC", "1800")
    base.setdefault("PM_RISK_DRAWDOWN_MIN_FRESH_OBS", "3")
    base.setdefault("PM_NH_MAX_END_DATE_MONTHS", "3")
    base.setdefault("PM_NH_MIN_RESOLUTION_ETA_SEC", "0")
    base.setdefault("PM_NH_MAX_RESOLUTION_ETA_SEC", "0")
    return base


def seed_runtime_settings_if_empty(engine: sa.Engine) -> None:
    """Insert non-secret defaults when the table has no rows."""
    with engine.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(runtime_settings_table)).scalar_one()
        if int(n) > 0:
            return
        defaults = _builtin_seed_defaults()
        # Merge live config.json if present (still non-secret only).
        cfg_path = Path(os.getenv("CONFIG_PATH", "config.json"))
        if cfg_path.is_file():
            try:
                with cfg_path.open(encoding="utf-8") as fp:
                    defaults.update(_defaults_from_config_json(json.load(fp)))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("runtime_settings_seed_config_json_failed: %s", exc)
        now = sa.func.now()
        for key, value in defaults.items():
            if key not in FIELD_BY_KEY or FIELD_BY_KEY[key].secret:
                continue
            conn.execute(runtime_settings_table.insert().values(key=key, value=value, updated_at=now))
        conn.commit()
    logger.info("runtime_settings_seeded", extra={"keys": len(defaults)})


def load_stored_settings(engine: sa.Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(runtime_settings_table.c.key, runtime_settings_table.c.value)).all()
    return {str(r[0]): str(r[1]) for r in rows}


def apply_runtime_settings(engine: sa.Engine | None) -> int:
    """Copy DB rows into os.environ. Returns number of keys applied."""
    if engine is None:
        return 0
    try:
        data = load_stored_settings(engine)
    except Exception as exc:
        logger.warning("runtime_settings_load_failed: %s", exc)
        return 0
    for k, v in data.items():
        if k not in FIELD_BY_KEY:
            continue
        os.environ[k] = v
    if data:
        logger.info("runtime_settings_applied", extra={"count": len(data)})
    return len(data)


def _validate_value(field: SettingField, raw: str) -> tuple[bool, str]:
    raw = (raw or "").strip()
    if field.kind == "str":
        return True, raw
    if field.kind == "bool":
        return True, "true" if _parse_bool(raw) else "false"
    if field.kind == "int":
        if not raw:
            return False, "Required"
        try:
            int(raw)
        except ValueError:
            return False, "Must be an integer"
        return True, raw
    if field.kind == "float":
        if not raw:
            return False, "Required"
        try:
            float(raw)
        except ValueError:
            return False, "Must be a number"
        return True, raw
    if field.kind == "choice":
        if raw not in field.choices:
            return False, "Invalid choice"
        return True, raw
    return True, raw


def validate_all_settings(data: dict[str, str]) -> tuple[bool, str]:
    """Validate merged key->value map (after apply semantics)."""
    from bot.config import NothingHappensConfig, _validate_nothing_happens_config

    mode = data.get("BOT_MODE", os.getenv("BOT_MODE", "paper")).strip().lower()
    if mode not in {"paper", "live"}:
        return False, "BOT_MODE must be paper or live"

    conn = {
        "host": data.get("PM_CONNECTION_HOST", "https://clob.polymarket.com"),
        "chain_id": int(data.get("PM_CONNECTION_CHAIN_ID", "137")),
        "signature_type": int(data.get("PM_CONNECTION_SIGNATURE_TYPE", "2")),
    }
    try:
        from bot.config import ExchangeConfig, _compute_live_send_enabled

        # Simulate env for live flag
        old: dict[str, str | None] = {}
        for k in ("BOT_MODE", "DRY_RUN", "LIVE_TRADING_ENABLED", "PRIVATE_KEY", "FUNDER_ADDRESS"):
            old[k] = os.environ.get(k)
        try:
            os.environ["BOT_MODE"] = data.get("BOT_MODE", os.getenv("BOT_MODE", "paper"))
            os.environ["DRY_RUN"] = data.get("DRY_RUN", os.getenv("DRY_RUN", "true"))
            os.environ["LIVE_TRADING_ENABLED"] = data.get(
                "LIVE_TRADING_ENABLED", os.getenv("LIVE_TRADING_ENABLED", "false")
            )
            os.environ["PRIVATE_KEY"] = data.get("PRIVATE_KEY", os.getenv("PRIVATE_KEY", ""))
            os.environ["FUNDER_ADDRESS"] = data.get("FUNDER_ADDRESS", os.getenv("FUNDER_ADDRESS", ""))
            live = _compute_live_send_enabled()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        ex = ExchangeConfig(
            host=str(conn["host"]),
            chain_id=int(conn["chain_id"]),
            signature_type=int(conn["signature_type"]),
            private_key=(data.get("PRIVATE_KEY") or os.getenv("PRIVATE_KEY") or "").strip() or None,
            funder_address=(data.get("FUNDER_ADDRESS") or os.getenv("FUNDER_ADDRESS") or "").strip() or None,
            live_send_enabled=live,
        )
        ex.validate()
    except Exception as exc:
        return False, str(exc)

    strat_map = {
        "market_refresh_interval_sec": int(data.get("PM_NH_MARKET_REFRESH_INTERVAL_SEC", "600")),
        "price_poll_interval_sec": int(data.get("PM_NH_PRICE_POLL_INTERVAL_SEC", "60")),
        "position_sync_interval_sec": int(data.get("PM_NH_POSITION_SYNC_INTERVAL_SEC", "60")),
        "order_dispatch_interval_sec": int(data.get("PM_NH_ORDER_DISPATCH_INTERVAL_SEC", "60")),
        "cash_pct_per_trade": float(data.get("PM_NH_CASH_PCT_PER_TRADE", "0.02")),
        "min_trade_amount": float(data.get("PM_NH_MIN_TRADE_AMOUNT", "5")),
        "fixed_trade_amount": float(data.get("PM_NH_FIXED_TRADE_AMOUNT_USD", "0")),
        "max_entry_price": float(data.get("PM_NH_MAX_ENTRY_PRICE", "0.65")),
        "allowed_slippage": float(data.get("PM_NH_ALLOWED_SLIPPAGE", "0.3")),
        "request_concurrency": int(data.get("PM_NH_REQUEST_CONCURRENCY", "4")),
        "buy_retry_count": int(data.get("PM_NH_BUY_RETRY_COUNT", "3")),
        "buy_retry_base_delay_sec": float(data.get("PM_NH_BUY_RETRY_BASE_DELAY_SEC", "1")),
        "max_backoff_sec": float(data.get("PM_NH_MAX_BACKOFF_SEC", "900")),
        "max_new_positions": int(data.get("PM_NH_MAX_NEW_POSITIONS", "-1")),
        "shutdown_on_max_new_positions": _parse_bool(
            data.get("PM_NH_SHUTDOWN_ON_MAX_NEW_POSITIONS", "false")
        ),
        "redeemer_interval_sec": int(data.get("PM_NH_REDEEMER_INTERVAL_SEC", "1800")),
        "max_end_date_months": int(data.get("PM_NH_MAX_END_DATE_MONTHS", "3")),
        "min_resolution_eta_sec": int(data.get("PM_NH_MIN_RESOLUTION_ETA_SEC", "0")),
        "max_resolution_eta_sec": int(data.get("PM_NH_MAX_RESOLUTION_ETA_SEC", "0")),
    }
    try:
        strat = NothingHappensConfig(**strat_map)
        _validate_nothing_happens_config(strat)
    except Exception as exc:
        return False, str(exc)

    workers = data.get("PM_BACKGROUND_EXECUTOR_WORKERS", "8").strip()
    if workers:
        try:
            w = int(workers)
            if w < 1:
                return False, "PM_BACKGROUND_EXECUTOR_WORKERS must be >= 1"
        except ValueError:
            return False, "PM_BACKGROUND_EXECUTOR_WORKERS must be an integer"

    ll = data.get("LOG_LEVEL", "INFO").strip().upper()
    if ll not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        return False, "LOG_LEVEL invalid"

    path = data.get("TRADE_LEDGER_PATH", "").strip()
    if not path:
        return False, "TRADE_LEDGER_PATH required"

    rpc = (data.get("POLYGON_RPC_URL") or "").strip()
    if (
        ex.live_send_enabled
        and ex.signature_type == 2
        and (ex.funder_address or "")
        and not rpc
    ):
        return False, "POLYGON_RPC_URL is required for live proxy (signature_type 2) redeemer path"

    return True, ""


def save_settings_from_form(
    engine: sa.Engine,
    form: dict[str, str],
) -> tuple[bool, str]:
    """Merge POST into DB. Secret empty = keep; non-secret empty = delete row."""
    merged = load_stored_settings(engine)
    for field in FIELDS:
        raw = form.get(field.key)
        if raw is None:
            continue
        raw = raw.strip()
        if field.secret:
            if not raw or raw == _SECRET_SENTINEL:
                continue
            ok, msg = _validate_value(field, raw)
            if not ok:
                return False, f"{field.label}: {msg}"
            merged[field.key] = msg
            continue
        if field.kind == "bool":
            merged[field.key] = "true" if _parse_bool(raw) else "false"
            continue
        if raw == "":
            merged.pop(field.key, None)
            continue
        ok, msg = _validate_value(field, raw)
        if not ok:
            return False, f"{field.label}: {msg}"
        merged[field.key] = msg

    ok, err = validate_all_settings(merged)
    if not ok:
        return False, err

    now = sa.func.now()
    with engine.begin() as conn:
        conn.execute(runtime_settings_table.delete())
        for k, v in merged.items():
            if k not in FIELD_BY_KEY:
                continue
            conn.execute(runtime_settings_table.insert().values(key=k, value=v, updated_at=now))
    return True, ""


def secret_fingerprint(value: str | None) -> str:
    if not value:
        return ""
    h = value.strip()
    if len(h) <= 8:
        return "********"
    return h[:4] + "…" + h[-4:]


SECTION_DOC_FRAGMENTS: dict[str, str] = {
    "Trading mode": "trading-mode",
    "Secrets": "secrets",
    "Polymarket connection": "polymarket-connection",
    "Paths & logging": "paths--logging",
    "Strategy": "strategy",
    "Risk": "risk",
}


def _ordered_sections() -> list[tuple[str, list[SettingField]]]:
    order: list[str] = []
    by_section: dict[str, list[SettingField]] = {}
    for f in FIELDS:
        if f.section not in by_section:
            order.append(f.section)
            by_section[f.section] = []
        by_section[f.section].append(f)
    return [(s, by_section[s]) for s in order]


def _section_tab_id(section: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")
    return s or "section"


def _field_help_and_value_hint_html(field: SettingField) -> str:
    from html import escape

    parts: list[str] = []
    if field.help:
        parts.append(f'<p class="field-help">{escape(field.help)}</p>')
    if field.value_hint:
        parts.append(f'<p class="field-value-hint">{escape(field.value_hint)}</p>')
    return "".join(parts)


def _render_field_row(
    field: SettingField,
    values: dict[str, Any],
    fingerprints: dict[str, str],
) -> str:
    from html import escape

    val = values.get(field.key, "")
    fid = escape(field.key)
    label = escape(field.label)
    hint_block = _field_help_and_value_hint_html(field)
    if field.secret:
        fp = fingerprints.get(field.key, "")
        fp_html = (
            f'<p class="field-fp muted">Currently stored: {escape(fp or "—")}</p>' if fp else ""
        )
        return (
            f'<div class="field"><label for="{fid}">{label}</label>'
            f'<input type="password" id="{fid}" name="{field.key}" '
            'autocomplete="off" placeholder="Leave blank to keep unchanged">'
            f"{fp_html}{hint_block}</div>"
        )
    if field.kind == "bool":
        checked_t = " selected" if val is True else ""
        checked_f = " selected" if val is not True else ""
        return (
            f'<div class="field"><label for="{fid}">{label}</label>'
            f'<select id="{fid}" name="{field.key}">'
            f'<option value="false"{checked_f}>false</option>'
            f'<option value="true"{checked_t}>true</option>'
            f"</select>{hint_block}</div>"
        )
    if field.kind == "choice":
        opts = []
        for c in field.choices:
            sel = " selected" if str(val) == str(c) else ""
            opts.append(f'<option value="{escape(str(c))}"{sel}>{escape(str(c))}</option>')
        return (
            f'<div class="field"><label for="{fid}">{label}</label>'
            f'<select id="{fid}" name="{field.key}">{"".join(opts)}</select>{hint_block}</div>'
        )
    sval = escape(str(val)) if val is not None else ""
    return (
        f'<div class="field"><label for="{fid}">{label}</label>'
        f'<input type="text" id="{fid}" name="{field.key}" value="{sval}">{hint_block}</div>'
    )


def render_settings_form_fields(values: dict[str, Any], fingerprints: dict[str, str]) -> str:
    """Build HTML inputs for all settings (no outer form tag).

    Sections are rendered as tabs (one panel per section) inside the same logical form;
    inactive panels use the ``hidden`` attribute until the user switches tabs.
    """
    from html import escape

    sections = _ordered_sections()
    parts: list[str] = []
    parts.append('<div class="settings-tabs-root" data-settings-tabs>')
    parts.append('<div class="settings-tablist" role="tablist" aria-label="Settings sections">')
    for i, (section, _) in enumerate(sections):
        tid = _section_tab_id(section)
        selected = "true" if i == 0 else "false"
        panel_id = f"panel-{tid}"
        parts.append(
            f'<button type="button" class="settings-tab" role="tab" id="tab-{tid}" '
            f'aria-selected="{selected}" aria-controls="{panel_id}" '
            f'data-tab-target="{panel_id}">{escape(section)}</button>'
        )
    parts.append("</div>")
    parts.append('<div class="settings-tabpanels">')
    for i, (section, fields) in enumerate(sections):
        tid = _section_tab_id(section)
        panel_id = f"panel-{tid}"
        hidden_attr = "" if i == 0 else ' hidden="hidden"'
        frag = SECTION_DOC_FRAGMENTS.get(section)
        doc_link = (
            f' <a class="help-section-link" href="/help/settings#{frag}" '
            'target="_blank" rel="noopener noreferrer" title="Open documentation">docs</a>'
            if frag
            else ""
        )
        parts.append(
            f'<div id="{panel_id}" class="settings-tabpanel" role="tabpanel" '
            f'aria-labelledby="tab-{tid}"{hidden_attr}>'
        )
        parts.append(f'<h2 class="section-title">{escape(section)}{doc_link}</h2>')
        parts.append('<div class="settings-grid">')
        for field in fields:
            parts.append(_render_field_row(field, values, fingerprints))
        parts.append("</div></div>")
    parts.append("</div></div>")
    return "\n".join(parts)


def build_form_values(engine: sa.Engine | None) -> dict[str, Any]:
    """For template: current value per key; secrets show placeholder when set."""
    stored: dict[str, str] = {}
    if engine is not None:
        try:
            stored = load_stored_settings(engine)
        except Exception:
            pass
    out: dict[str, Any] = {}
    fps: dict[str, str] = {}
    for field in FIELDS:
        v = stored.get(field.key, "")
        if field.secret:
            if v:
                out[field.key] = ""
                fps[field.key] = secret_fingerprint(v)
            else:
                out[field.key] = ""
                fps[field.key] = ""
        elif field.kind == "bool":
            out[field.key] = _parse_bool(v) if v else False
        else:
            out[field.key] = v
    return {"values": out, "fingerprints": fps}
