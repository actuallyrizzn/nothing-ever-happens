"""Paper wallet persistence in bot_state."""

from pathlib import Path

import pytest
import sqlalchemy as sa

from bot.db import create_engine, create_tables
from bot.exchange.paper import PaperExchangeClient
from bot.models import LimitOrderIntent, MarketOrderIntent, Side
from bot.paper_wallet import load_paper_state, save_paper_state


@pytest.fixture()
def paper_engine(tmp_path: Path) -> sa.Engine:
    db_path = tmp_path / "paper_test.sqlite"
    eng = create_engine(f"sqlite:///{db_path}")
    create_tables(eng)
    return eng


def test_save_and_load_roundtrip(paper_engine: sa.Engine) -> None:
    ex = PaperExchangeClient(
        persist_save=lambda s: save_paper_state(paper_engine, s),
        initial_state=None,
    )
    ex.place_market_order(
        MarketOrderIntent(
            token_id="tok1",
            side=Side.BUY,
            amount=10.0,
            reference_price=0.5,
        )
    )
    loaded = load_paper_state(paper_engine)
    assert loaded is not None
    assert loaded["collateral_balance"] < 100.0
    assert loaded["conditional_balances"].get("tok1", 0) > 0


def test_restart_rehydrates_client(paper_engine: sa.Engine) -> None:
    ex1 = PaperExchangeClient(
        persist_save=lambda s: save_paper_state(paper_engine, s),
        initial_state=load_paper_state(paper_engine),
    )
    ex1.place_limit_order(
        LimitOrderIntent(token_id="tokx", side=Side.BUY, price=0.4, size=5.0)
    )
    snap = load_paper_state(paper_engine)
    ex2 = PaperExchangeClient(
        persist_save=lambda s: save_paper_state(paper_engine, s),
        initial_state=snap,
    )
    assert len(ex2.get_open_orders("tokx")) == 1


def test_default_paper_state_row_missing(paper_engine: sa.Engine) -> None:
    assert load_paper_state(paper_engine) is None
    ex = PaperExchangeClient(persist_save=lambda s: save_paper_state(paper_engine, s), initial_state=None)
    assert ex.get_collateral_balance() == pytest.approx(100.0)

