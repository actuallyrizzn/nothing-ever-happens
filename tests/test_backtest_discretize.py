import pytest

from bot.backtest.discretize import discretize_p2, discretize_for_run
from bot.config import NothingHappensConfig


def test_discretize_p2_uses_grid_timestamps() -> None:
    points = [(1_700_000_000, 0.6), (1_700_000_030, 0.55), (1_700_000_120, 0.40)]
    out = discretize_p2(points, t_open=1_700_000_000, poll_interval_sec=60)
    assert out[0][0] == 1_700_000_000
    assert out[1][0] == 1_700_000_060
    assert out[1][1] == 0.55


def test_discretize_for_run_p2_requires_t_open() -> None:
    cfg = NothingHappensConfig(price_poll_interval_sec=60)
    with pytest.raises(ValueError, match="t_open"):
        discretize_for_run([(1, 0.5)], "P2", t_open=None, cfg=cfg)
