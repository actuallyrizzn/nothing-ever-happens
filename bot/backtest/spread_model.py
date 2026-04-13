from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadModelV0:
    """Tier A: treat ``p`` as a mid-like reference; shift toward the NO ask."""

    # Additive bump in probability units (e.g. 0.005 = half a cent).
    half_spread: float = 0.005


def no_ask_from_history_p(p: float, model: SpreadModelV0) -> float:
    """Synthetic NO best ask from history price ``p``."""
    x = float(p) + float(model.half_spread)
    return max(0.01, min(0.99, x))
