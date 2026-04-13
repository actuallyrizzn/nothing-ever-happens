from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bot.backtest.ingest import asdict_stats, run_ingest
from bot.backtest.run import run_backtest
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
    )
    print(json.dumps(asdict_stats(stats), indent=2))
    return 0 if not stats.errors else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    report = validate_archive(Path(args.archive))
    write_validate_report(Path(args.archive), report)
    print(json.dumps({"ok": report.ok, "errors": report.errors, "warnings": report.warnings}, indent=2))
    return 0 if report.ok else 2


def _cmd_run(args: argparse.Namespace) -> int:
    summary = run_backtest(
        archive=Path(args.archive),
        config_path=Path(args.config_json) if args.config_json else None,
        initial_cash=args.initial_cash,
        out_dir=Path(args.out),
        half_spread=args.half_spread,
    )
    print(json.dumps(summary, indent=2))
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
    pi.add_argument("--force", action="store_true", help="Ignore checkpoint and re-fetch")
    pi.add_argument("--no-resume", action="store_true")
    pi.set_defaults(func=_cmd_ingest)

    pv = sub.add_parser("validate", help="Validate archive layout and price series")
    pv.add_argument("--archive", required=True)
    pv.set_defaults(func=_cmd_validate)

    pr = sub.add_parser("run", help="Run Tier-A first-hit scan (offline)")
    pr.add_argument("--archive", required=True)
    pr.add_argument("--config-json", default=None, help="Partial nothing_happens JSON")
    pr.add_argument("--initial-cash", type=float, default=10_000.0)
    pr.add_argument("--out", required=True, help="Output directory for summary + manifest")
    pr.add_argument("--half-spread", type=float, default=0.005)
    pr.set_defaults(func=_cmd_run)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
