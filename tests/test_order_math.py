import bot.exchange.polymarket_clob as polymarket_clob
from bot.order_math import (
    clamp_probability,
    market_buy_buffered_price,
    submitted_buy_price,
)


def test_clamp_matches_polymorph_module() -> None:
    assert clamp_probability(0.5) == 0.5
    assert clamp_probability(0) == 0.01
    assert clamp_probability(1) == 0.99
    assert clamp_probability(2) == 0.99


def test_submitted_buy_price_uses_cap_when_positive() -> None:
    assert submitted_buy_price(
        0.40,
        max_entry_price=0.65,
        allowed_slippage=0.30,
    ) == clamp_probability(0.65)


def test_submitted_buy_price_slippage_when_max_entry_non_positive() -> None:
    assert submitted_buy_price(
        0.40,
        max_entry_price=0.0,
        allowed_slippage=0.10,
    ) == clamp_probability(0.50)


def test_market_buy_buffered_price_matches_place_order_branch() -> None:
    assert market_buy_buffered_price(
        reference_price=0.40,
        allowed_slippage=0.05,
        price_cap=0.65,
    ) == clamp_probability(0.65)
    assert market_buy_buffered_price(
        reference_price=0.40,
        allowed_slippage=0.10,
        price_cap=None,
    ) == clamp_probability(0.50)


def test_polymorph_reexports_clamp() -> None:
    # Ensures exchange module still binds _clamp_probability for any legacy refs.
    assert polymarket_clob._clamp_probability(0.2) == clamp_probability(0.2)
