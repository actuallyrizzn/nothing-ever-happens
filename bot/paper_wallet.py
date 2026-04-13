"""Persist simulated paper exchange state in the bot SQLite (``bot_state`` table)."""

from __future__ import annotations

import json
import logging
from typing import Any

import sqlalchemy as sa

from bot.db import bot_state_table

logger = logging.getLogger(__name__)

PAPER_STATE_KEY = "paper_exchange_v1"
_SCHEMA_VERSION = 1


def default_paper_state() -> dict[str, Any]:
    """Fresh paper wallet (matches PaperExchangeClient defaults)."""
    return {
        "version": _SCHEMA_VERSION,
        "mid": 0.5,
        "tick_size": 0.01,
        "min_order_size": 1.0,
        "collateral_balance": 100.0,
        "conditional_balances": {},
        "open_orders": [],
        "counter": 0,
        "trades": [],
    }


def load_paper_state(engine: sa.Engine | None) -> dict[str, Any] | None:
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(bot_state_table.c.value).where(bot_state_table.c.key == PAPER_STATE_KEY)
            ).fetchone()
        if row is None or not str(row[0]).strip():
            return None
        data = json.loads(str(row[0]))
        if int(data.get("version", 0)) != _SCHEMA_VERSION:
            logger.warning("paper_wallet_unknown_version", extra={"version": data.get("version")})
            return None
        return data
    except (json.JSONDecodeError, OSError, sa.exc.SQLAlchemyError) as exc:
        logger.warning("paper_wallet_load_failed: %s", exc)
        return None


def save_paper_state(engine: sa.Engine | None, state: dict[str, Any]) -> None:
    if engine is None:
        return
    payload = json.dumps(state, separators=(",", ":"), sort_keys=True)
    now = sa.func.now()
    try:
        with engine.begin() as conn:
            conn.execute(
                bot_state_table.delete().where(bot_state_table.c.key == PAPER_STATE_KEY)
            )
            conn.execute(
                bot_state_table.insert().values(key=PAPER_STATE_KEY, value=payload, updated_at=now)
            )
    except sa.exc.SQLAlchemyError as exc:
        logger.warning("paper_wallet_save_failed: %s", exc)


def delete_paper_state(engine: sa.Engine | None) -> None:
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(bot_state_table.delete().where(bot_state_table.c.key == PAPER_STATE_KEY))
    except sa.exc.SQLAlchemyError as exc:
        logger.warning("paper_wallet_delete_failed: %s", exc)
