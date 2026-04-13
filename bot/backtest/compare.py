"""Tier A vs Tier B (or any two runs) comparison report — plan §Phase 4."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_compare_html(
    *,
    summary_a: dict[str, Any],
    summary_b: dict[str, Any],
    manifest_a: dict[str, Any] | None = None,
    manifest_b: dict[str, Any] | None = None,
) -> str:
    def row(label: str, va: Any, vb: Any) -> str:
        return (
            f"<tr><td>{label}</td><td>{va}</td><td>{vb}</td></tr>"
        )

    ma = manifest_a or {}
    mb = manifest_b or {}
    body_rows = [
        row("fidelity_tier", summary_a.get("fidelity_tier"), summary_b.get("fidelity_tier")),
        row("execution_fidelity", summary_a.get("execution_fidelity"), summary_b.get("execution_fidelity")),
        row("markets_total", summary_a.get("markets_total"), summary_b.get("markets_total")),
        row("markets_with_entry", summary_a.get("markets_with_entry"), summary_b.get("markets_with_entry")),
        row("pnl_usd_sum", summary_a.get("pnl_usd_sum_where_outcome_known"), summary_b.get("pnl_usd_sum_where_outcome_known")),
        row("max_dd_proxy", summary_a.get("max_drawdown_proxy_usd"), summary_b.get("max_drawdown_proxy_usd")),
        row("win_rate", summary_a.get("win_rate_where_outcome_known"), summary_b.get("win_rate_where_outcome_known")),
        row("manifest.half_spread", ma.get("half_spread"), mb.get("half_spread")),
        row("manifest.fee_bps", ma.get("fee_bps"), mb.get("fee_bps")),
        row("manifest.l2_archive", ma.get("l2_archive"), mb.get("l2_archive")),
    ]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Backtest compare</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; background: #111; color: #e0e0e0; }}
table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
th, td {{ border: 1px solid #444; padding: 8px 12px; text-align: left; }}
th {{ background: #222; }}
h1 {{ font-size: 1.25rem; }}
</style></head><body>
<h1>Backtest comparison</h1>
<table>
<tr><th>Metric</th><th>Run A</th><th>Run B</th></tr>
{"".join(body_rows)}
</table>
</body></html>"""


def write_compare_report(
    *,
    run_dir_a: Path,
    run_dir_b: Path,
    out_html: Path,
) -> None:
    sa = json.loads((Path(run_dir_a) / "summary.json").read_text(encoding="utf-8"))
    sb = json.loads((Path(run_dir_b) / "summary.json").read_text(encoding="utf-8"))
    ma_path = Path(run_dir_a) / "run_manifest.json"
    mb_path = Path(run_dir_b) / "run_manifest.json"
    ma = json.loads(ma_path.read_text(encoding="utf-8")) if ma_path.exists() else None
    mb = json.loads(mb_path.read_text(encoding="utf-8")) if mb_path.exists() else None
    html = build_compare_html(summary_a=sa, summary_b=sb, manifest_a=ma, manifest_b=mb)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
