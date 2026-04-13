import pytest

from bot.backtest.discretize import discretize_p1, discretize_p2, discretize_for_run
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


def test_discretize_p2_empty_and_non_positive_poll() -> None:
    assert discretize_p2([], t_open=1, poll_interval_sec=60) == []
    pts = [(1, 0.5)]
    assert discretize_p2(pts, t_open=1, poll_interval_sec=0) == discretize_p1(pts)


def test_discretize_p2_t_open_after_series() -> None:
    assert discretize_p2([(1, 0.5), (2, 0.4)], t_open=100, poll_interval_sec=10) == []


def test_discretize_for_run_p3_and_unknown() -> None:
    cfg = NothingHappensConfig(price_poll_interval_sec=60)
    pts = [(1, 0.5), (2, 0.4)]
    assert discretize_for_run(pts, "P3", t_open=None, cfg=cfg) == discretize_p1(pts)
    assert discretize_for_run(pts, "hybrid", t_open=None, cfg=cfg) == discretize_p1(pts)
    with pytest.raises(ValueError, match="Unknown discretization"):
        discretize_for_run(pts, "unknown_policy", t_open=1, cfg=cfg)
