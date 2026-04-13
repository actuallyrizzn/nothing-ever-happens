from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from bot.backtest.config_load import load_nothing_happens_for_backtest
from bot.backtest.first_hit import first_executable_moment
from bot.backtest.hashing import canonical_json_hash
from bot.backtest.spread_model import SpreadModelV0
from bot.backtest.predicate import WalletState


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parents[2],
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except OSError:
        pass
    return None


def _load_price_points(archive: Path, token_id: str) -> list[tuple[int, float]]:
    path = archive / "prices" / f"{token_id}.parquet"
    if not path.exists():
        return []
    table = pq.read_table(path, columns=["t", "p"])
    ts = table["t"].to_pylist()
    ps = table["p"].to_pylist()
    return [(int(t), float(p)) for t, p in zip(ts, ps)]


def run_backtest(
    *,
    archive: Path,
    config_path: Path | None,
    initial_cash: float,
    out_dir: Path,
    half_spread: float = 0.005,
) -> dict[str, Any]:
    """Single-market-style scan: each universe row evaluated independently."""
    archive = Path(archive).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_nothing_happens_for_backtest(config_path)
    spread = SpreadModelV0(half_spread=half_spread)
    cash0 = max(0.0, float(initial_cash))

    u_path = archive / "universe.parquet"
    if not u_path.exists():
        raise FileNotFoundError(f"Missing {u_path}")

    ut = pq.read_table(u_path)
    rows = ut.to_pylist()
    per_market: list[dict[str, Any]] = []
    skipped_reasons: dict[str, int] = {}
    entries = 0

    for row in rows:
        token_id = str(row.get("no_token_id") or "")
        slug = str(row.get("slug") or token_id[:16])
        coverage = str(row.get("coverage_class") or "unknown")
        if coverage == "empty_history":
            skipped_reasons["empty_history"] = skipped_reasons.get("empty_history", 0) + 1
            per_market.append(
                {
                    "slug": slug,
                    "no_token_id": token_id,
                    "t_first": None,
                    "entered": False,
                    "fill_price": None,
                    "pnl_usd": None,
                    "reason_skip": "empty_history",
                    "coverage_class": coverage,
                }
            )
            continue

        points = _load_price_points(archive, token_id)
        if not points:
            skipped_reasons["missing_prices_file"] = (
                skipped_reasons.get("missing_prices_file", 0) + 1
            )
            per_market.append(
                {
                    "slug": slug,
                    "no_token_id": token_id,
                    "t_first": None,
                    "entered": False,
                    "fill_price": None,
                    "pnl_usd": None,
                    "reason_skip": "missing_prices_file",
                    "coverage_class": coverage,
                }
            )
            continue

        mos = float(row.get("min_order_size") or 0.0)
        bos = mos
        # Independent capital per market (single_market_only semantics).
        wallet = WalletState(cash_usd=cash0)
        hit = first_executable_moment(
            points,
            cfg=cfg,
            wallet=wallet,
            spread=spread,
            market_min_order_size=mos,
            book_min_order_size=bos,
            assume_infinite_book_depth=True,
            safe_notional_usd=None,
        )

        pnl_usd: float | None = None
        entered = hit.t_first is not None
        if entered and hit.target_notional is not None and hit.fill_price:
            entries += 1
            fp = float(hit.fill_price)
            tgt = float(hit.target_notional)
            shares = tgt / fp if fp > 0 else 0.0
            outcome = row.get("outcome_no_wins")
            if outcome is None:
                pnl_usd = None
            else:
                won = bool(outcome)
                payoff_per_share = 1.0 if won else 0.0
                pnl_usd = shares * payoff_per_share - tgt
        elif not entered and hit.reason_skip:
            skipped_reasons[hit.reason_skip] = skipped_reasons.get(hit.reason_skip, 0) + 1

        per_market.append(
            {
                "slug": slug,
                "no_token_id": token_id,
                "t_first": hit.t_first,
                "entered": entered,
                "fill_price": hit.fill_price,
                "pnl_usd": pnl_usd,
                "reason_skip": None if entered else hit.reason_skip,
                "coverage_class": coverage,
            }
        )

    # Write per_market.jsonl (simple, no extra parquet dep for readers)
    pm_path = out_dir / "per_market.jsonl"
    with open(pm_path, "w", encoding="utf-8") as f:
        for r in per_market:
            f.write(json.dumps(r, default=str) + "\n")

    manifest_payload = {
        "fidelity_tier": "A",
        "execution_fidelity": "indicative",
        "spread_model": "SpreadModelV0",
        "half_spread": half_spread,
        "portfolio_sequencing": "single_market_only",
        "scheduling_mode": "coarse_bar",
        "drawdown_mode": "off",
        "risk_metrics_partial": True,
        "sim_balance_recovery": False,
        "live_path_excluded": [
            "balance_recovery",
            "book_depth",
            "kill_switch",
            "resolution_eta_live_clock",
        ],
        "assume_infinite_book_depth": True,
        "archive": str(archive),
        "calibration_run_id": "uncalibrated",
        "git_commit": _git_sha(),
        "created_at": time.time(),
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2), encoding="utf-8"
    )

    pnl_sum = sum(r["pnl_usd"] for r in per_market if r["pnl_usd"] is not None)
    summary = {
        "markets_total": len(rows),
        "markets_with_entry": entries,
        "markets_skipped_reason_counts": skipped_reasons,
        "pnl_usd_sum_where_outcome_known": pnl_sum,
        "fidelity_tier": "A",
        "execution_fidelity": "indicative",
        "universe_manifest_hash": canonical_json_hash(rows),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
