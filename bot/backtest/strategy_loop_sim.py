"""``scheduling_mode=strategy_loop`` — skip bars until ``order_dispatch_interval_sec`` elapses (§5.5)."""

from __future__ import annotations

from bot.config import NothingHappensConfig

from bot.backtest.first_hit import FirstHitResult
from bot.backtest.predicate import WalletState, entry_predicate
from bot.backtest.spread_model import SpreadModelV0, no_ask_from_history_p


def first_executable_moment_strategy_loop(
    points: list[tuple[int, float]],
    *,
    cfg: NothingHappensConfig,
    wallet: WalletState,
    spread: SpreadModelV0,
    market_min_order_size: float,
    book_min_order_size: float,
    assume_infinite_book_depth: bool,
    safe_notional_usd: float | None,
    use_l2_best_ask_direct: bool = False,
) -> FirstHitResult:
    """Like coarse scan but after a failed evaluation, advance to first bar with
    ``t >= t_fail + order_dispatch_interval_sec`` (live dispatch cadence proxy).
    """
    if not points:
        return FirstHitResult(None, None, None, None, "empty_series")

    dispatch = max(1, int(cfg.order_dispatch_interval_sec))
    last_reason = "predicate_never_true"
    i = 0
    n = len(points)

    while i < n:
        t_i, p_i = points[i]
        no_ask = float(p_i) if use_l2_best_ask_direct else no_ask_from_history_p(p_i, spread)
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
            return FirstHitResult(
                t_first=int(t_i),
                no_ask_at_hit=no_ask,
                fill_price=no_ask,
                target_notional=check.target_notional,
                reason_skip=None,
            )
        t_next = int(t_i) + dispatch
        i += 1
        while i < n and points[i][0] < t_next:
            i += 1

    return FirstHitResult(None, None, None, None, last_reason)
