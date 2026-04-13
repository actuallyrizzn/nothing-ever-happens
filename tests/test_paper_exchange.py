"""Unit tests for PaperExchangeClient."""

from __future__ import annotations

import time

import pytest

from bot.exchange.paper import PaperExchangeClient
from bot.models import LimitOrderIntent, MarketOrderIntent, Side


@pytest.mark.unit
def test_paper_bootstrap_mid_rules_and_order_book() -> None:
    ex = PaperExchangeClient(initial_mid=0.55, tick_size=0.02, min_order_size=2.0, initial_collateral_balance=50.0)
    assert ex.bootstrap_live_trading(None) is None
    assert ex.get_mid_price("tok") == 0.55
    ex.set_mid(0.60)
    assert ex.get_mid_price("tok") == 0.60
    rules = ex.get_market_rules("tok")
    assert rules.tick_size == 0.02 and rules.min_order_size == 2.0
    book = ex.get_order_book("tok")
    assert book.token_id == "tok" and book.bids and book.asks


@pytest.mark.unit
def test_paper_limit_order_open_cancel() -> None:
    ex = PaperExchangeClient()
    ex.warm_token_cache("t1")
    assert ex.prepare_sell("t1") is True
    r = ex.place_limit_order(
        LimitOrderIntent(token_id="t1", side=Side.BUY, price=0.4, size=10.0),
    )
    assert r.status == "simulated" and r.order_id.startswith("paper-")
    open_t1 = ex.get_open_orders("t1")
    assert len(open_t1) == 1
    assert ex.get_order(r.order_id) is not None
    assert ex.cancel_order(r.order_id) is True
    assert ex.get_open_orders("t1") == []
    assert ex.cancel_all() is True


@pytest.mark.unit
def test_paper_market_buy_and_sell() -> None:
    ex = PaperExchangeClient(initial_mid=0.5, initial_collateral_balance=1_000.0)
    buy = ex.place_market_order(
        MarketOrderIntent(token_id="nt", side=Side.BUY, amount=100.0, reference_price=0.5),
    )
    assert buy.status == "matched"
    assert ex.get_conditional_balance("nt") > 0
    bal_after_buy = ex.get_collateral_balance()
    assert bal_after_buy < 1_000.0
    sell = ex.place_market_order(
        MarketOrderIntent(token_id="nt", side=Side.SELL, amount=1_000.0, reference_price=0.5),
    )
    assert sell.status == "matched"
    assert ex.check_order_readiness(buy.raw["order"]).ready is True


@pytest.mark.unit
def test_paper_market_buy_uses_mid_when_no_reference() -> None:
    ex = PaperExchangeClient(initial_mid=0.48, initial_collateral_balance=50.0)
    r = ex.place_market_order(
        MarketOrderIntent(token_id="x", side=Side.BUY, amount=10.0, reference_price=None),
    )
    assert r.status == "matched"


@pytest.mark.unit
def test_paper_market_sell_capped_by_conditional_balance() -> None:
    ex = PaperExchangeClient(initial_mid=0.5, initial_collateral_balance=500.0)
    ex.place_market_order(
        MarketOrderIntent(token_id="y", side=Side.BUY, amount=50.0, reference_price=0.5),
    )
    cond = ex.get_conditional_balance("y")
    sell = ex.place_market_order(
        MarketOrderIntent(token_id="y", side=Side.SELL, amount=1e9, reference_price=0.5),
    )
    assert sell.status == "matched"
    assert ex.get_conditional_balance("y") < cond


@pytest.mark.unit
def test_paper_get_trades_after_timestamp() -> None:
    ex = PaperExchangeClient(initial_mid=0.5, initial_collateral_balance=100.0)
    ex.place_market_order(
        MarketOrderIntent(token_id="z", side=Side.BUY, amount=5.0, reference_price=0.5),
    )
    trades = ex.get_trades("z")
    assert len(trades) == 1
    before = int(time.time()) - 10_000
    filtered = ex.get_trades("z", after_timestamp=before)
    assert len(filtered) >= 1
