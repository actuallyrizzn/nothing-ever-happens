from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bot.backtest.config_load import load_nothing_happens_for_backtest
from bot.backtest.discretize import discretize_for_run
from bot.backtest.first_hit import FirstHitResult, first_executable_moment
from bot.backtest.hashing import canonical_json_hash
from bot.backtest.predicate import WalletState, entry_predicate
from bot.backtest.run_context import PriceRunContext, build_price_context, fee_usd
from bot.backtest.spread_model import SpreadModelV0, no_ask_from_history_p
from bot.backtest.strategy_loop_sim import first_executable_moment_strategy_loop
from bot.backtest.validate import load_validate_report
from bot.config import NothingHappensConfig
from bot.risk_controls import RiskConfig, RiskController


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


def _nh_config_fingerprint(cfg: NothingHappensConfig) -> str:
    d = dataclasses.asdict(cfg)
    return canonical_json_hash(d)


def _archive_fingerprint(archive: Path) -> str:
    h = hashlib.sha256()
    for name in ("universe.parquet", "ingest_metadata.json"):
        p = archive / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


@dataclass
class BacktestRunOptions:
    archive: Path
    out_dir: Path
    config_path: Path | None = None
    initial_cash: float = 10_000.0
    half_spread: float = 0.005
    fidelity_tier: str = "A"
    discretization: str = "P1"
    t_open_policy_expected: str | None = None
    portfolio_sequencing: str = "single_market_only"
    scheduling_mode: str = "coarse_bar"
    drawdown_mode: str = "off"
    sim_balance_recovery: bool = False
    min_markets_with_data: int | None = None
    min_bars_per_market: int | None = None
    require_validated_manifest: bool = False
    calibration_run_id: str = "uncalibrated"
    l2_archive: Path | None = None
    fee_bps: float = 0.0
    simulate_risk_caps: bool = False


def _resolution_blocks_pnl(status: str | None) -> bool:
    if not status:
        return False
    s = str(status).strip().lower()
    return s in {"void", "disputed"}


def _apply_gates(
    *,
    rows: list[dict[str, Any]],
    ctx: PriceRunContext,
    min_markets_with_data: int | None,
    min_bars_per_market: int | None,
) -> None:
    min_bars = int(min_bars_per_market) if min_bars_per_market is not None else 1
    ok_count = 0
    for row in rows:
        cov = str(row.get("coverage_class") or "")
        if cov == "empty_history":
            continue
        tid = str(row.get("no_token_id") or "")
        pts = ctx.load_raw(tid)
        if len(pts) >= min_bars:
            ok_count += 1
    if min_markets_with_data is not None and ok_count < int(min_markets_with_data):
        raise ValueError(
            f"Quality gate: markets_with_data={ok_count} < min_markets_with_data={min_markets_with_data} "
            f"(min_bars_per_market={min_bars})"
        )


def _max_dd_single_market(
    points: list[tuple[int, float]],
    *,
    t_first: int,
    shares: float,
    cash_after_entry: float,
    spread: SpreadModelV0,
    l2_direct: bool,
) -> float:
    """Largest peak-to-trough drop in proxy equity (§5.8 step_mtm)."""
    max_dd = 0.0
    peak: float | None = None
    trough: float | None = None
    for t_i, p_i in points:
        if t_i < t_first:
            continue
        mark = float(p_i) if l2_direct else no_ask_from_history_p(p_i, spread)
        equity = cash_after_entry + shares * mark
        if peak is None:
            peak = trough = equity
            continue
        if equity > peak:
            peak = equity
            trough = equity
        if equity < trough:
            trough = equity
        max_dd = max(max_dd, peak - trough)
    return max_dd


def _scan_first_hit(
    points: list[tuple[int, float]],
    *,
    cfg: NothingHappensConfig,
    wallet: WalletState,
    spread: SpreadModelV0,
    mos: float,
    scheduling_mode: str,
    l2_direct: bool,
) -> FirstHitResult:
    sm = scheduling_mode.strip().lower()
    if sm == "strategy_loop":
        return first_executable_moment_strategy_loop(
            points,
            cfg=cfg,
            wallet=wallet,
            spread=spread,
            market_min_order_size=mos,
            book_min_order_size=mos,
            assume_infinite_book_depth=True,
            safe_notional_usd=None,
            use_l2_best_ask_direct=l2_direct,
        )
    return first_executable_moment(
        points,
        cfg=cfg,
        wallet=wallet,
        spread=spread,
        market_min_order_size=mos,
        book_min_order_size=mos,
        assume_infinite_book_depth=True,
        safe_notional_usd=None,
        use_l2_best_ask_direct=l2_direct,
    )


def _run_single_market_only(
    *,
    rows: list[dict[str, Any]],
    ctx: PriceRunContext,
    cash0: float,
    options: BacktestRunOptions,
) -> tuple[list[dict[str, Any]], int, dict[str, int], float | None]:
    per_market: list[dict[str, Any]] = []
    skipped_reasons: dict[str, int] = {}
    entries = 0
    max_dd_global: float | None = None

    for row in rows:
        token_id = str(row.get("no_token_id") or "")
        slug = str(row.get("slug") or token_id[:16])
        coverage = str(row.get("coverage_class") or "unknown")
        if options.t_open_policy_expected and str(row.get("t_open_source") or "") != options.t_open_policy_expected:
            raise ValueError(
                f"t_open_policy mismatch for {slug!r}: "
                f"expected {options.t_open_policy_expected!r}, got {row.get('t_open_source')!r}"
            )

        if coverage == "empty_history":
            skipped_reasons["empty_history"] = skipped_reasons.get("empty_history", 0) + 1
            per_market.append(
                _pm_row(
                    slug,
                    token_id,
                    coverage,
                    None,
                    False,
                    None,
                    None,
                    "empty_history",
                    None,
                )
            )
            continue

        raw_points = ctx.load_raw(token_id)
        if not raw_points:
            skipped_reasons["missing_prices_file"] = skipped_reasons.get("missing_prices_file", 0) + 1
            per_market.append(
                _pm_row(slug, token_id, coverage, None, False, None, None, "missing_prices_file", None)
            )
            continue

        t_open = row.get("t_open")
        t_open_i = int(t_open) if t_open is not None else None
        try:
            points = discretize_for_run(
                raw_points,
                options.discretization,
                t_open=t_open_i,
                cfg=ctx.cfg,
            )
        except ValueError as exc:
            skipped_reasons["discretize_error"] = skipped_reasons.get("discretize_error", 0) + 1
            per_market.append(
                _pm_row(slug, token_id, coverage, None, False, None, None, str(exc), None)
            )
            continue

        mos = float(row.get("min_order_size") or 0.0)
        wallet = WalletState(cash_usd=cash0)
        hit = _scan_first_hit(
            points,
            cfg=ctx.cfg,
            wallet=wallet,
            spread=ctx.spread,
            mos=mos,
            scheduling_mode=options.scheduling_mode,
            l2_direct=ctx.l2_direct,
        )
        if hit.t_first is not None and hit.target_notional is not None and ctx.risk is not None:
            now_us = int(hit.t_first) * 1_000_000
            ok_r, rr = ctx.risk.can_open_trade(now_us, slug, float(hit.target_notional))
            if not ok_r:
                hit = FirstHitResult(None, None, None, None, f"risk_block:{rr}")
            else:
                ctx.risk.on_open_trade(slug, float(hit.target_notional), now_us)

        res_status = str(row.get("resolution_status") or "unknown")
        block_pnl = _resolution_blocks_pnl(res_status)

        pnl_usd: float | None = None
        entered = hit.t_first is not None
        dd: float | None = None

        if entered and hit.target_notional is not None and hit.fill_price:
            entries += 1
            fp = float(hit.fill_price)
            tgt = float(hit.target_notional)
            shares = tgt / fp if fp > 0 else 0.0
            cash_after = cash0 - tgt
            outcome = row.get("outcome_no_wins")
            if outcome is None or block_pnl:
                pnl_usd = None
            else:
                won = bool(outcome)
                payoff_per_share = 1.0 if won else 0.0
                fe = fee_usd(tgt, ctx.fee_bps)
                pnl_usd = shares * payoff_per_share - tgt - fe

            if options.drawdown_mode == "step_mtm" and hit.t_first is not None:
                dd = _max_dd_single_market(
                    raw_points,
                    t_first=int(hit.t_first),
                    shares=shares,
                    cash_after_entry=cash_after,
                    spread=ctx.spread,
                    l2_direct=ctx.l2_direct,
                )
                max_dd_global = dd if max_dd_global is None else max(max_dd_global, dd)
            if ctx.risk is not None and hit.target_notional is not None:
                end_us = int(raw_points[-1][0]) * 1_000_000 if raw_points else int(hit.t_first) * 1_000_000
                ctx.risk.on_close_trade(
                    slug,
                    float(hit.target_notional),
                    float(pnl_usd or 0.0),
                    end_us,
                )
        elif not entered and hit.reason_skip:
            skipped_reasons[hit.reason_skip] = skipped_reasons.get(hit.reason_skip, 0) + 1

        if not entered:
            skip_reason = hit.reason_skip
        elif pnl_usd is None:
            skip_reason = "resolution_void_or_disputed" if block_pnl else "unknown_outcome"
        else:
            skip_reason = None

        per_market.append(
            _pm_row(
                slug,
                token_id,
                coverage,
                hit.t_first,
                entered,
                hit.fill_price,
                pnl_usd,
                skip_reason,
                dd,
            )
        )

    return per_market, entries, skipped_reasons, max_dd_global


def _pm_row(
    slug: str,
    token_id: str,
    coverage: str,
    t_first: int | None,
    entered: bool,
    fill_price: float | None,
    pnl_usd: float | None,
    reason_skip: str | None,
    max_dd_proxy: float | None,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "no_token_id": token_id,
        "t_first": t_first,
        "entered": entered,
        "fill_price": fill_price,
        "pnl_usd": pnl_usd,
        "reason_skip": reason_skip,
        "coverage_class": coverage,
        "max_drawdown_proxy_usd": max_dd_proxy,
    }


def _events_from_rows(
    rows: list[dict[str, Any]],
    ctx: PriceRunContext,
    discretization: str,
) -> list[tuple[int, str, dict[str, Any], float]]:
    """Sorted (t, slug, row, p) for global sequencing."""
    events: list[tuple[int, str, dict[str, Any], float]] = []
    for row in rows:
        token_id = str(row.get("no_token_id") or "")
        slug = str(row.get("slug") or token_id[:16])
        cov = str(row.get("coverage_class") or "")
        if cov == "empty_history":
            continue
        raw = ctx.load_raw(token_id)
        if not raw:
            continue
        t_open = row.get("t_open")
        t_open_i = int(t_open) if t_open is not None else None
        try:
            pts = discretize_for_run(raw, discretization, t_open=t_open_i, cfg=ctx.cfg)
        except ValueError:
            continue
        for t_i, p_i in pts:
            events.append((int(t_i), slug, row, float(p_i)))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def _run_portfolio_shared_wallet(
    *,
    rows: list[dict[str, Any]],
    ctx: PriceRunContext,
    cash0: float,
    options: BacktestRunOptions,
    time_ordered: bool,
) -> tuple[list[dict[str, Any]], int, dict[str, int], float | None]:
    """serial_by_slug (row order) or time_ordered_global."""
    def _slug_row(r: dict[str, Any]) -> tuple[str, str]:
        tid = str(r.get("no_token_id") or "")
        slug = str(r.get("slug") or tid[:16])
        return slug, tid

    per_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        slug, tid = _slug_row(r)
        cov = str(r.get("coverage_class") or "unknown")
        if cov == "empty_history":
            per_map[slug] = _pm_row(slug, tid, cov, None, False, None, None, "empty_history", None)
        elif not tid or not ctx.load_raw(tid):
            per_map[slug] = _pm_row(slug, tid, cov, None, False, None, None, "missing_prices_file", None)
        else:
            per_map[slug] = _pm_row(slug, tid, cov, None, False, None, None, "no_entry", None)

    cash = float(cash0)
    entered_slugs: set[str] = set()
    hits: dict[str, FirstHitResult] = {}
    max_dd_global: float | None = None

    if not time_ordered:
        for row in rows:
            slug, tid = _slug_row(row)
            if slug in entered_slugs:
                continue
            cov = str(row.get("coverage_class") or "")
            if cov == "empty_history" or not tid:
                continue
            raw = ctx.load_raw(tid)
            if not raw:
                continue
            t_open = row.get("t_open")
            t_open_i = int(t_open) if t_open is not None else None
            try:
                points = discretize_for_run(raw, options.discretization, t_open=t_open_i, cfg=ctx.cfg)
            except ValueError:
                continue
            mos = float(row.get("min_order_size") or 0.0)
            hit = _scan_first_hit(
                points,
                cfg=ctx.cfg,
                wallet=WalletState(cash_usd=cash),
                spread=ctx.spread,
                mos=mos,
                scheduling_mode=options.scheduling_mode,
                l2_direct=ctx.l2_direct,
            )
            if hit.t_first is not None and hit.target_notional is not None and ctx.risk is not None:
                now_us = int(hit.t_first) * 1_000_000
                ok_r, rr = ctx.risk.can_open_trade(now_us, slug, float(hit.target_notional))
                if not ok_r:
                    hit = FirstHitResult(None, None, None, None, f"risk_block:{rr}")
                else:
                    ctx.risk.on_open_trade(slug, float(hit.target_notional), now_us)
            if hit.t_first is not None and hit.target_notional is not None:
                entered_slugs.add(slug)
                hits[slug] = hit
                cash -= float(hit.target_notional)
    else:
        events = _events_from_rows(rows, ctx, options.discretization)
        for t_i, slug, row, p_i in events:
            tid = str(row.get("no_token_id") or "")
            if slug in entered_slugs or not tid:
                continue
            cov = str(row.get("coverage_class") or "")
            if cov == "empty_history":
                continue
            no_ask = float(p_i) if ctx.l2_direct else no_ask_from_history_p(p_i, ctx.spread)
            mos = float(row.get("min_order_size") or 0.0)
            check = entry_predicate(
                no_ask=no_ask,
                cfg=ctx.cfg,
                wallet=WalletState(cash_usd=cash),
                market_min_order_size=mos,
                book_min_order_size=mos,
                assume_infinite_book_depth=True,
                safe_notional_usd=None,
            )
            if check.ok and check.target_notional is not None:
                if ctx.risk is not None:
                    now_us = int(t_i) * 1_000_000
                    ok_r, rr = ctx.risk.can_open_trade(now_us, slug, float(check.target_notional))
                    if not ok_r:
                        continue
                    ctx.risk.on_open_trade(slug, float(check.target_notional), now_us)
                entered_slugs.add(slug)
                hits[slug] = FirstHitResult(
                    t_first=int(t_i),
                    no_ask_at_hit=no_ask,
                    fill_price=no_ask,
                    target_notional=check.target_notional,
                    reason_skip=None,
                )
                cash -= float(check.target_notional)

    entries = 0
    skipped_reasons: dict[str, int] = {}
    running_cash = float(cash0)
    for row in rows:
        slug, tid = _slug_row(row)
        cov = str(row.get("coverage_class") or "unknown")
        hit = hits.get(slug)
        if hit is None or hit.t_first is None:
            r0 = per_map[slug]
            if r0.get("reason_skip") not in {"empty_history", "missing_prices_file"}:
                skipped_reasons["no_entry"] = skipped_reasons.get("no_entry", 0) + 1
            continue
        entries += 1
        fp = float(hit.fill_price or 0.0)
        tgt = float(hit.target_notional or 0.0)
        shares = tgt / fp if fp > 0 else 0.0
        cash_after_entry = running_cash - tgt
        running_cash = cash_after_entry
        res_status = str(row.get("resolution_status") or "unknown")
        block_pnl = _resolution_blocks_pnl(res_status)
        outcome = row.get("outcome_no_wins")
        pnl_usd: float | None = None
        if outcome is not None and not block_pnl:
            won = bool(outcome)
            fe = fee_usd(tgt, ctx.fee_bps)
            pnl_usd = shares * (1.0 if won else 0.0) - tgt - fe
        elif block_pnl:
            pnl_usd = None
        if pnl_usd is None:
            skip_reason = "resolution_void_or_disputed" if block_pnl else "unknown_outcome_or_blocked"
        else:
            skip_reason = None
        dd: float | None = None
        if options.drawdown_mode == "step_mtm":
            raw = ctx.load_raw(tid)
            if raw and hit.t_first is not None:
                dd = _max_dd_single_market(
                    raw,
                    t_first=int(hit.t_first),
                    shares=shares,
                    cash_after_entry=cash_after_entry,
                    spread=ctx.spread,
                    l2_direct=ctx.l2_direct,
                )
                max_dd_global = dd if max_dd_global is None else max(max_dd_global, dd)
        if ctx.risk is not None and hit.target_notional is not None:
            raw = ctx.load_raw(tid)
            end_us = int(raw[-1][0]) * 1_000_000 if raw else int(hit.t_first) * 1_000_000
            ctx.risk.on_close_trade(slug, float(hit.target_notional), float(pnl_usd or 0.0), end_us)
        per_map[slug] = _pm_row(
            slug,
            tid,
            cov,
            hit.t_first,
            True,
            hit.fill_price,
            pnl_usd,
            skip_reason,
            dd,
        )

    order_slugs = [_slug_row(r)[0] for r in rows]
    per_market = [per_map[s] for s in order_slugs if s in per_map]
    return per_market, entries, skipped_reasons, max_dd_global


def run_backtest(options: BacktestRunOptions) -> dict[str, Any]:
    archive = Path(options.archive).resolve()
    out_dir = Path(options.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if options.require_validated_manifest:
        rep = load_validate_report(archive)
        if rep is None:
            raise ValueError(
                "require_validated_manifest: missing validate_report.json — run validate first"
            )
        if not rep.get("ok"):
            raise ValueError("require_validated_manifest: last validate_report.json has ok=false")

    cfg = load_nothing_happens_for_backtest(options.config_path)
    spread = SpreadModelV0(half_spread=options.half_spread)
    cash0 = max(0.0, float(options.initial_cash))
    risk = RiskController(RiskConfig.from_env()) if options.simulate_risk_caps else None
    ctx = build_price_context(
        archive=archive,
        fidelity_tier=options.fidelity_tier,
        l2_archive=Path(options.l2_archive) if options.l2_archive else None,
        cfg=cfg,
        spread=spread,
        risk=risk,
        fee_bps=options.fee_bps,
    )

    u_path = archive / "universe.parquet"
    if not u_path.exists():
        raise FileNotFoundError(f"Missing {u_path}")

    ut = pq.read_table(u_path)
    rows = ut.to_pylist()

    _apply_gates(
        rows=rows,
        ctx=ctx,
        min_markets_with_data=options.min_markets_with_data,
        min_bars_per_market=options.min_bars_per_market,
    )

    mode = options.portfolio_sequencing.strip().lower()
    if mode in {"single_market_only", "single"}:
        per_market, entries, skipped_reasons, max_dd = _run_single_market_only(
            rows=rows,
            ctx=ctx,
            cash0=cash0,
            options=options,
        )
    elif mode in {"serial_by_slug", "serial"}:
        per_market, entries, skipped_reasons, max_dd = _run_portfolio_shared_wallet(
            rows=rows,
            ctx=ctx,
            cash0=cash0,
            options=options,
            time_ordered=False,
        )
    elif mode in {"time_ordered_global", "global"}:
        per_market, entries, skipped_reasons, max_dd = _run_portfolio_shared_wallet(
            rows=rows,
            ctx=ctx,
            cash0=cash0,
            options=options,
            time_ordered=True,
        )
    else:
        raise ValueError(f"Unknown portfolio_sequencing: {options.portfolio_sequencing!r}")

    pm_jsonl = out_dir / "per_market.jsonl"
    with open(pm_jsonl, "w", encoding="utf-8") as f:
        for r in per_market:
            f.write(json.dumps(r, default=str) + "\n")

    pm_parquet = out_dir / "per_market.parquet"
    pq.write_table(pa.Table.from_pylist(per_market), pm_parquet, compression="zstd")

    risk_partial = options.drawdown_mode != "step_mtm" or max_dd is None
    live_excluded = [
        "balance_recovery",
        "book_depth",
        "kill_switch",
        "resolution_eta_live_clock",
    ]
    if options.drawdown_mode == "off":
        live_excluded.append("step_mtm_drawdown")
    if options.portfolio_sequencing.strip().lower() not in {"single_market_only", "single"}:
        if not options.simulate_risk_caps:
            live_excluded.append("portfolio_risk_caps_not_simulated")

    exec_fid = (
        "l2_best_ask_parquet"
        if options.fidelity_tier.strip().upper() == "B"
        else "indicative"
    )
    manifest_payload = {
        "fidelity_tier": options.fidelity_tier,
        "execution_fidelity": exec_fid,
        "l2_archive": str(options.l2_archive) if options.l2_archive else None,
        "fee_bps": options.fee_bps,
        "simulate_risk_caps": options.simulate_risk_caps,
        "spread_model": "SpreadModelV0",
        "half_spread": options.half_spread,
        "discretization": options.discretization,
        "portfolio_sequencing": options.portfolio_sequencing,
        "scheduling_mode": options.scheduling_mode,
        "drawdown_mode": options.drawdown_mode,
        "risk_metrics_partial": risk_partial,
        "sim_balance_recovery": options.sim_balance_recovery,
        "live_path_excluded": sorted(set(live_excluded)),
        "assume_infinite_book_depth": True,
        "archive": str(archive),
        "calibration_run_id": options.calibration_run_id,
        "config_hash": _nh_config_fingerprint(cfg),
        "archive_fingerprint": _archive_fingerprint(archive),
        "git_commit": _git_sha(),
        "created_at": time.time(),
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2), encoding="utf-8"
    )

    resolved_pnls = [float(r["pnl_usd"]) for r in per_market if r.get("pnl_usd") is not None]
    pnl_sum = sum(resolved_pnls)
    win_rate = None
    if resolved_pnls:
        win_rate = sum(1 for x in resolved_pnls if x > 0) / len(resolved_pnls)
    excluded_empty = sum(1 for r in per_market if r.get("coverage_class") == "empty_history")
    excluded_partial = sum(1 for r in per_market if r.get("coverage_class") == "partial_range")
    res_counts: dict[str, int] = {}
    for r in rows:
        rs = str(r.get("resolution_status") or "unknown")
        res_counts[rs] = res_counts.get(rs, 0) + 1
    universe_rules: set[str] = {str(r.get("universe_rule") or "unspecified") for r in rows}
    ur = universe_rules.pop() if len(universe_rules) == 1 else "mixed"
    if len(universe_rules) > 0:
        ur = "mixed"

    summary = {
        "markets_total": len(rows),
        "markets_with_entry": entries,
        "excluded_empty_history": excluded_empty,
        "excluded_partial_range": excluded_partial,
        "markets_skipped_reason_counts": skipped_reasons,
        "pnl_usd_sum_where_outcome_known": pnl_sum,
        "win_rate_where_outcome_known": win_rate,
        "max_drawdown_proxy_usd": max_dd,
        "fidelity_tier": options.fidelity_tier,
        "execution_fidelity": exec_fid,
        "universe_manifest_hash": canonical_json_hash(rows),
        "universe_rule": ur,
        "resolution_status_counts": res_counts,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

