from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq


@dataclass
class ValidateReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tokens_checked: int = 0


def _looks_like_unix_seconds(t: int) -> bool:
    # Reject millisecond timestamps (13 digits) and nonsense.
    if t <= 0:
        return False
    if t > 10_000_000_000:  # > year ~2286 in seconds — likely ms
        return False
    if t < 1_000_000_000:  # before ~2001
        return False
    return True


def validate_archive(archive: Path) -> ValidateReport:
    """Validate ``universe.parquet`` vs ``prices/*.parquet`` (monotonic t, keys)."""
    archive = Path(archive).resolve()
    report = ValidateReport(ok=True)
    u_path = archive / "universe.parquet"
    if not u_path.exists():
        report.ok = False
        report.errors.append("missing_universe_parquet")
        return report

    ut = pq.read_table(u_path)
    cols = set(ut.column_names)
    if "no_token_id" not in cols:
        report.ok = False
        report.errors.append("universe_missing_no_token_id_column")
        return report

    tokens = ut["no_token_id"].to_pylist()
    for token_id in tokens:
        token_id = str(token_id)
        report.tokens_checked += 1
        p_path = archive / "prices" / f"{token_id}.parquet"
        if not p_path.exists():
            report.ok = False
            report.errors.append(f"missing_price_file:{token_id}")
            continue

        try:
            table = pq.read_table(p_path, columns=["t", "p"])
        except Exception as exc:
            report.ok = False
            report.errors.append(f"read_parquet:{token_id}:{exc}")
            continue

        n = table.num_rows
        if n == 0:
            report.warnings.append(f"empty_series:{token_id}")
            continue

        ts = [int(x) for x in table["t"].to_pylist()]
        for i in range(1, len(ts)):
            if ts[i] <= ts[i - 1]:
                report.ok = False
                report.errors.append(f"non_monotonic_t:{token_id}")
                break
        for t in ts:
            if not _looks_like_unix_seconds(t):
                report.ok = False
                report.errors.append(f"suspicious_t_unit:{token_id}:{t}")
                break

    return report


def write_validate_report(archive: Path, report: ValidateReport) -> None:
    out = Path(archive) / "validate_report.json"
    payload = {
        "ok": report.ok,
        "errors": report.errors,
        "warnings": report.warnings,
        "tokens_checked": report.tokens_checked,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
