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
    if t <= 0:
        return False
    if t > 10_000_000_000:
        return False
    if t < 1_000_000_000:
        return False
    return True


def validate_archive(archive: Path) -> ValidateReport:
    """Validate ``universe.parquet`` vs ``prices/*.parquet`` (§6.4)."""
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
    starts = ut["ingest_start_ts"].to_pylist() if "ingest_start_ts" in cols else None
    ends = ut["ingest_end_ts"].to_pylist() if "ingest_end_ts" in cols else None
    coverages = ut["coverage_class"].to_pylist() if "coverage_class" in cols else None

    for idx, token_id in enumerate(tokens):
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
        if coverages is not None and idx < len(coverages):
            cov = str(coverages[idx] or "")
            if cov not in {"empty_history"} and n == 0:
                report.warnings.append(f"coverage_mismatch_empty_file:{token_id}")

        if n == 0:
            report.warnings.append(f"empty_series:{token_id}")
            continue

        ts = [int(x) for x in table["t"].to_pylist()]
        for i in range(1, len(ts)):
            if ts[i] < ts[i - 1]:
                report.ok = False
                report.errors.append(f"non_monotonic_t:{token_id}")
                break
            if ts[i] == ts[i - 1]:
                report.ok = False
                report.errors.append(f"duplicate_t:{token_id}:{ts[i]}")
                break
        for t in ts:
            if not _looks_like_unix_seconds(t):
                report.ok = False
                report.errors.append(f"suspicious_t_unit:{token_id}:{t}")
                break

        if starts is not None and ends is not None and ts and idx < len(starts) and idx < len(ends):
            st = starts[idx]
            et = ends[idx]
            if st is not None and et is not None:
                try:
                    st_i, et_i = int(st), int(et)
                    t_min, t_max = ts[0], ts[-1]
                    if t_min > st_i + 60 or t_max < et_i - 60:
                        report.warnings.append(
                            f"partial_range_vs_ingest_window:{token_id}:t[{t_min},{t_max}] wanted[{st_i},{et_i}]"
                        )
                except (TypeError, ValueError):
                    pass

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


def load_validate_report(archive: Path) -> dict[str, Any] | None:
    p = Path(archive) / "validate_report.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
