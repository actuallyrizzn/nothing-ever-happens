"""Offline backtest: CLOB prices-history archive, first-hit scan, validation CLI."""

from bot.backtest.first_hit import FirstHitResult, first_executable_moment
from bot.backtest.run import BacktestRunOptions, run_backtest

__all__ = ["BacktestRunOptions", "FirstHitResult", "first_executable_moment", "run_backtest"]
