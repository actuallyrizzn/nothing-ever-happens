from __future__ import annotations

from dataclasses import dataclass

from bot.config import NothingHappensConfig
from bot.order_math import submitted_buy_price


@dataclass(frozen=True)
class WalletState:
    """Single-market cash model (portfolio modes come later)."""

    cash_usd: float


@dataclass(frozen=True)
class EntryCheckResult:
    ok: bool
    reason: str
    target_notional: float = 0.0
    submitted_buy_price: float = 0.0


def target_notional_for_entry(
    *,
    cfg: NothingHappensConfig,
    cash_balance: float,
    submitted_price: float,
    market_min_order_size: float,
    book_min_order_size: float,
) -> float:
    """Match ``NothingHappensStrategy._target_notional`` (no book depth cap here)."""
    base_notional = (
        cfg.fixed_trade_amount
        if cfg.fixed_trade_amount > 0
        else max(cash_balance * cfg.cash_pct_per_trade, cfg.min_trade_amount)
    )
    minimum_shares = max(0.0, market_min_order_size, book_min_order_size)
    if minimum_shares <= 0 or submitted_price <= 0:
        return base_notional
    return max(base_notional, minimum_shares * submitted_price)


def entry_predicate(
    *,
    no_ask: float,
    cfg: NothingHappensConfig,
    wallet: WalletState,
    market_min_order_size: float,
    book_min_order_size: float,
    assume_infinite_book_depth: bool,
    safe_notional_usd: float | None,
) -> EntryCheckResult:
    """Whether we would queue an entry at this bar (Tier A, no risk/kill-switch)."""
    if no_ask <= 0:
        return EntryCheckResult(False, "no_ask_nonpositive")
    if no_ask > cfg.max_entry_price:
        return EntryCheckResult(False, "above_max_entry")

    sub = submitted_buy_price(
        no_ask,
        max_entry_price=cfg.max_entry_price,
        allowed_slippage=cfg.allowed_slippage,
    )
    cash_balance = max(0.0, wallet.cash_usd)
    target = target_notional_for_entry(
        cfg=cfg,
        cash_balance=cash_balance,
        submitted_price=sub,
        market_min_order_size=market_min_order_size,
        book_min_order_size=book_min_order_size,
    )
    if target > cash_balance + 1e-9:
        return EntryCheckResult(False, "insufficient_cash", target_notional=target, submitted_buy_price=sub)

    if not assume_infinite_book_depth:
        if safe_notional_usd is None:
            return EntryCheckResult(False, "safe_notional_required_when_depth_on")
        if safe_notional_usd + 1e-9 < target:
            return EntryCheckResult(False, "insufficient_depth", target_notional=target, submitted_buy_price=sub)

    return EntryCheckResult(True, "ok", target_notional=target, submitted_buy_price=sub)
