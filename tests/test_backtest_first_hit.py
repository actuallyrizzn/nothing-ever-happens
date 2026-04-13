from bot.backtest.first_hit import first_executable_moment
from bot.backtest.spread_model import SpreadModelV0
from bot.backtest.predicate import WalletState
from bot.config import NothingHappensConfig


def test_first_hit_finds_first_bar_in_range() -> None:
    cfg = NothingHappensConfig(max_entry_price=0.99, min_trade_amount=1.0, cash_pct_per_trade=0.5)
    wallet = WalletState(cash_usd=1000.0)
    spread = SpreadModelV0(half_spread=0.0)
    points = [(100, 0.50), (200, 0.40), (300, 0.70)]
    hit = first_executable_moment(
        points,
        cfg=cfg,
        wallet=wallet,
        spread=spread,
        market_min_order_size=0.0,
        book_min_order_size=0.0,
    )
    assert hit.t_first == 100
    assert hit.no_ask_at_hit == 0.50
    assert hit.target_notional is not None


def test_first_hit_respects_max_entry() -> None:
    cfg = NothingHappensConfig(max_entry_price=0.35, min_trade_amount=1.0, cash_pct_per_trade=0.5)
    wallet = WalletState(cash_usd=1000.0)
    spread = SpreadModelV0(half_spread=0.0)
    points = [(100, 0.50), (200, 0.30)]
    hit = first_executable_moment(
        points,
        cfg=cfg,
        wallet=wallet,
        spread=spread,
        market_min_order_size=0.0,
        book_min_order_size=0.0,
    )
    assert hit.t_first == 200
    assert hit.no_ask_at_hit == 0.30


def test_empty_series() -> None:
    cfg = NothingHappensConfig()
    hit = first_executable_moment(
        [],
        cfg=cfg,
        wallet=WalletState(100.0),
        spread=SpreadModelV0(),
        market_min_order_size=0.0,
        book_min_order_size=0.0,
    )
    assert hit.t_first is None
    assert hit.reason_skip == "empty_series"
