from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from bot.config import NothingHappensConfig


def merge_nothing_happens_config(
    base: NothingHappensConfig | None,
    overrides: dict[str, Any],
) -> NothingHappensConfig:
    """Apply only known ``NothingHappensConfig`` fields from ``overrides``."""
    b = base or NothingHappensConfig()
    names = {f.name for f in dataclasses.fields(NothingHappensConfig)}
    filtered = {k: v for k, v in overrides.items() if k in names}
    return dataclasses.replace(b, **filtered)


def load_nothing_happens_for_backtest(path: Path | None) -> NothingHappensConfig:
    """Load partial or full JSON object of strategy fields; missing keys use defaults."""
    if path is None:
        return NothingHappensConfig()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config JSON must be an object")
    # Allow either a bare object or {"strategies": {"nothing_happens": {...}}}
    if "strategies" in raw:
        strategies = raw["strategies"]
        if not isinstance(strategies, dict):
            raise ValueError("strategies must be an object")
        nh = strategies.get("nothing_happens")
        if nh is None:
            raise ValueError("missing strategies.nothing_happens")
        if not isinstance(nh, dict):
            raise ValueError("strategies.nothing_happens must be an object")
        raw = nh
    return merge_nothing_happens_config(None, raw)
