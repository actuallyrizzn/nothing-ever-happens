from __future__ import annotations

from dataclasses import dataclass

from bot.config import NothingHappensConfig

from bot.backtest.predicate import WalletState, entry_predicate
from bot.backtest.spread_model import SpreadModelV0, no_ask_from_history_p


@dataclass(frozen=True)
class FirstHitResult:
    t_first: int | None
    no_ask_at_hit: float | None
    fill_price: float | None
    target_notional: float | None
    reason_skip: str | None


def first_executable_moment(
    points: list[tuple[int, float]],
    *,
    cfg: NothingHappensConfig,
    wallet: WalletState,
    spread: SpreadModelV0,
    market_min_order_size: float,
    book_min_order_size: float,
    assume_infinite_book_depth: bool = True,
    safe_notional_usd: float | None = None,
) -> FirstHitResult:
    """P1 data-native scan: first bar where entry predicate holds.

    ``points`` must be sorted by ``t`` ascending.
    """
    if not points:
        return FirstHitResult(None, None, None, None, "empty_series")

    last_reason = "predicate_never_true"
    for t_i, p_i in points:
        no_ask = no_ask_from_history_p(p_i, spread)
        check = entry_predicate(
            no_ask=no_ask,
            cfg=cfg,
            wallet=wallet,
            market_min_order_size=market_min_order_size,
            book_min_order_size=book_min_order_size,
            assume_infinite_book_depth=assume_infinite_book_depth,
            safe_notional_usd=safe_notional_usd,
        )
        last_reason = check.reason
        if check.ok:
            # Tier A: fill proxy = observable ask proxy at decision time.
            return FirstHitResult(
                t_first=int(t_i),
                no_ask_at_hit=no_ask,
                fill_price=no_ask,
                target_notional=check.target_notional,
                reason_skip=None,
            )

    return FirstHitResult(None, None, None, None, last_reason)
