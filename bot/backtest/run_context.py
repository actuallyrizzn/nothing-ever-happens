from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bot.backtest.historical import TierAParquetSource, TierBParquetSource
from bot.backtest.spread_model import SpreadModelV0
from bot.config import NothingHappensConfig
from bot.risk_controls import RiskController


@dataclass
class PriceRunContext:
    """Per-run price loading + Tier B / risk flags."""

    archive: Path
    load_raw: Callable[[str], list[tuple[int, float]]]
    l2_direct: bool
    cfg: NothingHappensConfig
    spread: SpreadModelV0
    risk: RiskController | None
    fee_bps: float


def build_price_context(
    *,
    archive: Path,
    fidelity_tier: str,
    l2_archive: Path | None,
    cfg: NothingHappensConfig,
    spread: SpreadModelV0,
    risk: RiskController | None,
    fee_bps: float,
) -> PriceRunContext:
    tier = fidelity_tier.strip().upper()
    if tier == "A":
        src = TierAParquetSource(archive)
        return PriceRunContext(
            archive=archive,
            load_raw=src.load_no_ask_series,
            l2_direct=False,
            cfg=cfg,
            spread=spread,
            risk=risk,
            fee_bps=fee_bps,
        )
    if tier == "B":
        if l2_archive is None:
            raise ValueError("Tier B requires --l2-archive pointing to Parquet L2 root (see bot/backtest/historical.py)")
        l2 = Path(l2_archive).resolve()
        if not l2.is_dir():
            raise ValueError(f"l2-archive is not a directory: {l2}")
        src = TierBParquetSource(l2)
        return PriceRunContext(
            archive=archive,
            load_raw=src.load_no_ask_series,
            l2_direct=True,
            cfg=cfg,
            spread=spread,
            risk=risk,
            fee_bps=fee_bps,
        )
    raise ValueError(f"Unknown fidelity tier {fidelity_tier!r} (use A or B)")


def fee_usd(notional: float, fee_bps: float) -> float:
    return max(0.0, float(notional)) * max(0.0, float(fee_bps)) / 10_000.0
