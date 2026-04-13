"""Pluggable historical price sources — Tier A (prices-history Parquet) vs Tier B (L2 / best-ask Parquet)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pyarrow.parquet as pq


class HistoricalPriceSource(Protocol):
    def load_no_ask_series(self, token_id: str) -> list[tuple[int, float]]:
        """Return sorted ``(t_unix, no_best_ask_proxy)``."""
        ...


class TierAParquetSource:
    """``archive/prices/{token_id}.parquet`` with ``t``, ``p`` (history mid/last — Tier A semantics)."""

    def __init__(self, archive: Path) -> None:
        self.archive = Path(archive)

    def load_no_ask_series(self, token_id: str) -> list[tuple[int, float]]:
        path = self.archive / "prices" / f"{token_id}.parquet"
        if not path.exists():
            return []
        table = pq.read_table(path, columns=["t", "p"])
        ts = table["t"].to_pylist()
        ps = table["p"].to_pylist()
        return [(int(t), float(p)) for t, p in zip(ts, ps)]


class TierBParquetSource:
    """Minute (or coarser) L2 snapshot archive: ``l2_root/{token_id}.parquet``.

    Required columns: ``t`` (unix seconds), ``best_ask`` (float NO best ask).
    Optional: ``best_bid`` (ignored for entry predicate v1).
    """

    def __init__(self, l2_root: Path) -> None:
        self.l2_root = Path(l2_root)

    def load_no_ask_series(self, token_id: str) -> list[tuple[int, float]]:
        path = self.l2_root / f"{token_id}.parquet"
        if not path.exists():
            return []
        table = pq.read_table(path, columns=["t", "best_ask"])
        ts = table["t"].to_pylist()
        asks = table["best_ask"].to_pylist()
        return [(int(t), float(a)) for t, a in zip(ts, asks)]
