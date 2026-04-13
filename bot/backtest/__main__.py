from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bot.backtest.calibrate import run_tier_a_calibration
from bot.backtest.ingest import asdict_stats, run_ingest
from bot.backtest.compare import write_compare_report
from bot.backtest.run import BacktestRunOptions, run_backtest
from bot.backtest.validate import validate_archive, write_validate_report


def _cmd_ingest(args: argparse.Namespace) -> int:
    stats = run_ingest(
        archive=Path(args.archive),
        universe_path=Path(args.universe),
        host=args.host,
        fidelity=args.fidelity,
        interval=args.interval,
        max_requests_per_10s=args.max_req_per_10s,
        force=args.force,
        resume=not args.no_resume,
        max_gb=args.max_gb,
    )
    print(json.dumps(asdict_stats(stats), indent=2))
    return 0 if not stats.errors else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    report = validate_archive(Path(args.archive))
    write_validate_report(Path(args.archive), report)
    print(json.dumps({"ok": report.ok, "errors": report.errors, "warnings": report.warnings}, indent=2))
    return 0 if report.ok else 2


def _cmd_calibrate(args: argparse.Namespace) -> int:
    tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
    out = Path(args.out_json) if args.out_json else None
    payload = run_tier_a_calibration(
        host=args.host,
        token_ids=tokens,
        half_spread=args.half_spread,
        out_json=out,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if not payload.get("errors") else 1


def _cmd_compare(args: argparse.Namespace) -> int:
    write_compare_report(
        run_dir_a=Path(args.run_a),
        run_dir_b=Path(args.run_b),
        out_html=Path(args.out_html),
    )
    print(str(Path(args.out_html).resolve()))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        summary = run_backtest(
            BacktestRunOptions(
                archive=Path(args.archive),
                out_dir=Path(args.out),
                config_path=Path(args.config_json) if args.config_json else None,
                initial_cash=args.initial_cash,
                half_spread=args.half_spread,
                fidelity_tier=args.tier,
                discretization=args.discretization,
                t_open_policy_expected=args.t_open_expected,
                portfolio_sequencing=args.portfolio_sequencing,
                scheduling_mode=args.scheduling_mode,
                drawdown_mode=args.drawdown_mode,
                sim_balance_recovery=args.sim_balance_recovery,
                min_markets_with_data=args.min_markets_with_data,
                min_bars_per_market=args.min_bars_per_market,
                require_validated_manifest=args.require_validated_manifest,
                calibration_run_id=args.calibration_run_id,
                l2_archive=Path(args.l2_archive) if args.l2_archive else None,
                fee_bps=args.fee_bps,
                simulate_risk_caps=args.simulate_risk_caps,
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 4
    print(json.dumps(summary, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m bot.backtest", description="Backtest archive tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="Fetch prices-history into an archive")
    pi.add_argument("--archive", required=True, help="Archive root directory")
    pi.add_argument("--universe", required=True, help="JSONL universe (one object per line)")
    pi.add_argument("--host", default="https://clob.polymarket.com")
    pi.add_argument("--fidelity", type=int, default=1)
    pi.add_argument("--interval", default=None)
    pi.add_argument("--max-req-per-10s", type=int, default=800)
    pi.add_argument("--max-gb", type=float, default=None, help="Abort if cumulative Parquet size exceeds this")
    pi.add_argument("--force", action="store_true", help="Ignore checkpoint and re-fetch")
    pi.add_argument("--no-resume", action="store_true")
    pi.set_defaults(func=_cmd_ingest)

    pv = sub.add_parser("validate", help="Validate archive layout and price series")
    pv.add_argument("--archive", required=True)
    pv.set_defaults(func=_cmd_validate)

    pc = sub.add_parser("calibrate", help="Tier A: compare history p vs /book best ask (plan 2.4)")
    pc.add_argument("--host", default="https://clob.polymarket.com")
    pc.add_argument(
        "--tokens",
        required=True,
        help="Comma-separated NO token ids",
    )
    pc.add_argument("--half-spread", type=float, default=0.005)
    pc.add_argument("--out-json", default=None, help="Write full calibration payload")
    pc.set_defaults(func=_cmd_calibrate)

    pr = sub.add_parser("run", help="Run Tier-A first-hit scan (offline)")
    pr.add_argument("--archive", required=True)
    pr.add_argument("--config-json", default=None, help="Partial nothing_happens JSON")
    pr.add_argument("--initial-cash", type=float, default=10_000.0)
    pr.add_argument("--out", required=True, help="Output directory for summary + manifest")
    pr.add_argument("--half-spread", type=float, default=0.005)
    pr.add_argument("--tier", default="A", choices=["A", "B"])
    pr.add_argument(
        "--discretization",
        default="P1",
        help="P1 (data-native), P2 (poll-aligned; needs t_open on rows), P3 (hybrid→P1 scan)",
    )
    pr.add_argument(
        "--t-open-expected",
        default=None,
        help="If set, fail when universe row t_open_source differs",
    )
    pr.add_argument(
        "--portfolio-sequencing",
        default="single_market_only",
        help="single_market_only | serial_by_slug | time_ordered_global",
    )
    pr.add_argument(
        "--scheduling-mode",
        default="coarse_bar",
        choices=["coarse_bar", "strategy_loop"],
    )
    pr.add_argument(
        "--drawdown-mode",
        default="off",
        choices=["off", "step_mtm"],
    )
    pr.add_argument("--sim-balance-recovery", action="store_true")
    pr.add_argument(
        "--min-markets-with-data",
        type=int,
        default=None,
        help="Abort if fewer markets pass min bars gate",
    )
    pr.add_argument(
        "--min-bars-per-market",
        type=int,
        default=None,
        help="Minimum price bars per market for gate (default 1)",
    )
    pr.add_argument(
        "--require-validated-manifest",
        action="store_true",
        help="Require archive/validate_report.json with ok=true",
    )
    pr.add_argument(
        "--calibration-run-id",
        default="uncalibrated",
        help="Label for Tier A calibration run (metadata)",
    )
    pr.add_argument(
        "--l2-archive",
        default=None,
        help="Tier B: directory of per-token L2 Parquet files (t, best_ask)",
    )
    pr.add_argument(
        "--fee-bps",
        type=float,
        default=0.0,
        help="Fee in basis points applied where outcome is known",
    )
    pr.add_argument(
        "--simulate-risk-caps",
        action="store_true",
        help="Simulate RiskController gates from env (same as live)",
    )
    pr.set_defaults(func=_cmd_run)

    pcmp = sub.add_parser("compare", help="HTML report comparing two run directories (summary.json)")
    pcmp.add_argument("--run-a", required=True, dest="run_a", help="First run output directory")
    pcmp.add_argument("--run-b", required=True, dest="run_b", help="Second run output directory")
    pcmp.add_argument("--out-html", required=True, dest="out_html", help="Write comparison HTML here")
    pcmp.set_defaults(func=_cmd_compare)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
