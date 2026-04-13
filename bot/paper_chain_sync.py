"""Build a paper-wallet snapshot from live Polymarket / Polygon data (read-only)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from bot.config import ExchangeConfig, load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient
from bot.paper_wallet import default_paper_state

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"


def resolve_trading_wallet_address(exchange_cfg: ExchangeConfig) -> str | None:
    if exchange_cfg.signature_type in {1, 2} and exchange_cfg.funder_address:
        return str(exchange_cfg.funder_address).strip() or None
    if exchange_cfg.signature_type == 0 and exchange_cfg.private_key:
        try:
            from eth_account import Account

            return str(Account.from_key(exchange_cfg.private_key).address)
        except Exception:
            return None
    return None


def _fetch_positions(wallet: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for redeemable in ("true", "false"):
        qs = urllib.parse.urlencode(
            {"user": wallet, "redeemable": redeemable, "sizeThreshold": "0"}
        )
        url = f"{DATA_API_BASE}/positions?{qs}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nothing-ever-happens-paper-sync"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("paper_chain_positions_http_failed: %s", exc)
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(data)
    return out


def build_snapshot_from_chain() -> dict[str, Any]:
    """Collateral from CLOB balance API; conditional shares from Polymarket Data API positions."""
    exchange_cfg, _ = load_nothing_happens_config()
    wallet = resolve_trading_wallet_address(exchange_cfg)
    if not wallet:
        raise ValueError(
            "Cannot resolve wallet address (set PRIVATE_KEY and/or FUNDER_ADDRESS for your account type)."
        )
    if not exchange_cfg.private_key:
        raise ValueError("PRIVATE_KEY is required to query CLOB collateral via the API client.")

    base = default_paper_state()
    clob = PolymarketClobExchangeClient(exchange_cfg, allow_trading=False)
    collateral = float(clob.get_collateral_balance())
    base["collateral_balance"] = max(0.0, collateral)

    balances: dict[str, float] = {}
    for p in _fetch_positions(wallet):
        asset = str(p.get("asset") or "").strip()
        if not asset:
            continue
        try:
            sz = float(p.get("size") or 0.0)
        except (TypeError, ValueError):
            continue
        if sz > 1e-12:
            balances[asset] = sz
    base["conditional_balances"] = balances
    base["open_orders"] = []
    base["counter"] = 0
    base["trades"] = []
    logger.info(
        "paper_chain_sync_built",
        extra={"wallet": wallet[:10] + "…", "collateral": collateral, "tokens": len(balances)},
    )
    return base
