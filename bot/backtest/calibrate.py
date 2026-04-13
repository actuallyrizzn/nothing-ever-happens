"""Phase-0 Tier A calibration: history ``p`` vs live ``/book`` best ask (§2.4)."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from bot.backtest.clob_prices import (
    best_ask_from_book_raw,
    fetch_order_book_raw,
    fetch_prices_history,
    history_to_points,
)
from bot.backtest.spread_model import SpreadModelV0, no_ask_from_history_p


def run_tier_a_calibration(
    *,
    host: str,
    token_ids: list[str],
    half_spread: float = 0.005,
    out_json: Path | None = None,
) -> dict[str, Any]:
    """For each token, compare latest history ``p`` to current best ask (clock skew noted)."""
    spread = SpreadModelV0(half_spread=half_spread)
    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    for token_id in token_ids:
        token_id = str(token_id).strip()
        if not token_id:
            continue
        try:
            hist = fetch_prices_history(host=host, token_id=token_id, fidelity=1)
            pts = history_to_points(hist)
            if not pts:
                errors.append(f"empty_history:{token_id}")
                continue
            t_hist, p_hist = pts[-1]
            no_ask_proxy = no_ask_from_history_p(p_hist, spread)
            raw = fetch_order_book_raw(host=host, token_id=token_id)
            best_ask = best_ask_from_book_raw(raw)
            if best_ask is None:
                errors.append(f"no_asks_in_book:{token_id}")
                continue
            diff = no_ask_proxy - float(best_ask)
            samples.append(
                {
                    "token_id": token_id,
                    "history_t": t_hist,
                    "history_p": p_hist,
                    "no_ask_proxy": no_ask_proxy,
                    "book_best_ask": float(best_ask),
                    "diff_proxy_minus_ask": diff,
                    "book_timestamp": raw.get("timestamp"),
                }
            )
            time.sleep(0.15)
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
            errors.append(f"{token_id}:{exc}")

    diffs = [float(s["diff_proxy_minus_ask"]) for s in samples]
    stats_block: dict[str, Any] = {}
    if diffs:
        stats_block = {
            "n": len(diffs),
            "mean": statistics.mean(diffs),
            "median": statistics.median(diffs),
            "stdev": statistics.stdev(diffs) if len(diffs) > 1 else 0.0,
            "min": min(diffs),
            "max": max(diffs),
        }

    payload = {
        "history_p_semantics_note": "https://docs.polymarket.com/developers/CLOB/timeseries — compared to GET /book best ask; not same timestamp.",
        "half_spread": half_spread,
        "generated_at": time.time(),
        "host": host,
        "samples": samples,
        "aggregate_diff_proxy_minus_ask": stats_block,
        "errors": errors,
    }
    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
