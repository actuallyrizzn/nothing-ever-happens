"""Phase 3: dashboard job queue, quotas, dataset registry."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import defaultdict, deque
from html import escape as html_escape
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from aiohttp import web

from bot.backtest.run import BacktestRunOptions, run_backtest
from bot.dashboard_auth import DashboardAuth


def _datasets_from_env() -> list[dict[str, str]]:
    raw = (os.getenv("BACKTEST_DATASETS_JSON") or "").strip()
    if raw:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("id") and x.get("path")]
    root = (os.getenv("BACKTEST_ARCHIVE_ROOT") or "").strip()
    if root and Path(root).is_dir():
        return [
            {"id": p.name, "path": str(p), "label": p.name}
            for p in sorted(Path(root).iterdir())
            if p.is_dir() and (p / "universe.parquet").exists()
        ]
    return []


class BacktestJobQueue:
    """In-memory jobs + global / per-user quotas."""

    def __init__(self, auth: DashboardAuth | None = None) -> None:
        self._auth = auth
        self._lock = asyncio.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="backtest")
        self._max_concurrent = max(1, int(os.getenv("BACKTEST_MAX_CONCURRENT", "2")))
        self._running = 0
        self._per_user_hour = max(1, int(os.getenv("BACKTEST_MAX_PER_USER_PER_HOUR", "20")))
        self._user_times: dict[str, deque[float]] = defaultdict(deque)
        self._job_root = Path(os.getenv("BACKTEST_JOB_DIR", "var/backtest-jobs")).resolve()

    def _enforce_local_only(self, payload: dict[str, Any]) -> bool:
        if os.getenv("BACKTEST_ENFORCE_LOCAL_ONLY", "1").strip().lower() not in {"1", "true", "yes"}:
            return True
        blob = json.dumps(payload)
        if "http://" in blob or "https://" in blob:
            return False
        return True

    def _rate_allow(self, uid: str) -> bool:
        now = time.time()
        cutoff = now - 3600.0
        dq = self._user_times[uid]
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq) < self._per_user_hour

    def _rate_record(self, uid: str) -> None:
        self._user_times[uid].append(time.time())

    def register_routes(self, app: web.Application) -> None:
        app.router.add_get("/admin/backtest", self._page_get)
        app.router.add_get("/api/backtest/datasets", self._datasets_get)
        app.router.add_post("/api/backtest/jobs", self._jobs_post)
        app.router.add_get("/api/backtest/jobs/{job_id}", self._job_get)

    async def _page_get(self, request: web.Request) -> web.StreamResponse:
        csrf = str(request.get("dashboard_csrf", ""))
        ds = _datasets_from_env()
        datasets_preview = html_escape(json.dumps(ds, indent=2))
        csrf_esc = html_escape(csrf)
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Backtest jobs</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; max-width: 720px; }}
label {{ display: block; margin-top: 12px; }}
textarea, select, input {{ width: 100%; box-sizing: border-box; }}
pre {{ background: #f4f4f4; padding: 12px; overflow: auto; }}
</style></head><body>
<h1>Backtest (archive-local)</h1>
<p>Jobs return <code>202</code> with a <code>job_id</code>; poll <code>/api/backtest/jobs/&lt;id&gt;</code>. With <code>BACKTEST_ENFORCE_LOCAL_ONLY=1</code>, JSON must not contain URLs.</p>
<h2>Datasets (env / scan)</h2>
<pre>{datasets_preview}</pre>
<form id="f">
<input type="hidden" name="csrf_token" value="{csrf_esc}">
<label>Dataset path (absolute)</label>
<input name="archive" required placeholder="/path/to/archive">
<label>Optional partial config JSON</label>
<textarea name="config_json" rows="4" placeholder='{{"max_entry_price": 0.6}}'></textarea>
<label>Portfolio sequencing</label>
<select name="portfolio_sequencing">
<option value="single_market_only">single_market_only</option>
<option value="serial_by_slug">serial_by_slug</option>
<option value="time_ordered_global">time_ordered_global</option>
</select>
<label>Scheduling</label>
<select name="scheduling_mode">
<option value="coarse_bar">coarse_bar</option>
<option value="strategy_loop">strategy_loop</option>
</select>
<label>Tier</label>
<select name="tier"><option value="A">A (prices-history archive)</option><option value="B">B (L2 parquet)</option></select>
<label>L2 archive dir (Tier B only)</label>
<input name="l2_archive" placeholder="/path/to/l2_parquet_root">
<label>Fee (basis points, applied where outcome known)</label>
<input name="fee_bps" type="number" step="0.1" value="0" min="0">
<label><input type="checkbox" name="simulate_risk_caps" value="1"> Simulate risk caps (RiskConfig.from_env)</label>
<button type="submit">Enqueue job</button>
</form>
<pre id="out"></pre>
<script>
document.getElementById("f").onsubmit = async (e) => {{
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = {{
    csrf_token: fd.get("csrf_token"),
    archive: fd.get("archive"),
    config_json: fd.get("config_json") || null,
    portfolio_sequencing: fd.get("portfolio_sequencing"),
    scheduling_mode: fd.get("scheduling_mode"),
    tier: fd.get("tier"),
    l2_archive: fd.get("l2_archive") || null,
    fee_bps: parseFloat(fd.get("fee_bps") || "0") || 0,
    simulate_risk_caps: fd.get("simulate_risk_caps") === "1",
  }};
  const r = await fetch("/api/backtest/jobs", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(body),
  }});
  document.getElementById("out").textContent = await r.text();
}};
</script>
<p><a href="/">Dashboard</a></p>
</body></html>"""
        return web.Response(text=html, content_type="text/html")

    async def _datasets_get(self, request: web.Request) -> web.Response:
        return web.json_response({"datasets": _datasets_from_env()})

    def _verify_api_csrf(self, request: web.Request, payload: dict[str, Any]) -> bool:
        if self._auth is None:
            return True
        from bot.dashboard_auth import SESSION_COOKIE, read_cookie

        tok = read_cookie(request, SESSION_COOKIE)
        sess = self._auth.read_session(tok)
        if sess is None:
            return False
        return self._auth.verify_csrf(sess, str(payload.get("csrf_token") or ""))

    async def _jobs_post(self, request: web.Request) -> web.Response:
        uid = str(request.get("dashboard_uid") or "anon")
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid_json"}, status=400)

        if not self._verify_api_csrf(request, payload):
            return web.json_response({"error": "csrf"}, status=403)

        if not self._enforce_local_only(payload):
            return web.json_response({"error": "local_only_violation"}, status=400)

        async with self._lock:
            if not self._rate_allow(uid):
                return web.Response(
                    status=429,
                    text=json.dumps({"error": "per_user_hourly_limit"}),
                    content_type="application/json",
                    headers={"Retry-After": "3600"},
                )
            if self._running >= self._max_concurrent:
                return web.Response(
                    status=429,
                    text=json.dumps({"error": "max_concurrent"}),
                    content_type="application/json",
                    headers={"Retry-After": "60"},
                )
            self._rate_record(uid)
            self._running += 1

        job_id = str(uuid.uuid4())
        out_dir = self._job_root / job_id
        cfg_path = None
        cfg_raw = payload.get("config_json")
        if isinstance(cfg_raw, str) and cfg_raw.strip():
            out_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = out_dir / "request_config.json"
            cfg_path.write_text(cfg_raw, encoding="utf-8")

        fee_raw = payload.get("fee_bps", 0.0)
        try:
            fee_bps = float(fee_raw)
        except (TypeError, ValueError):
            fee_bps = 0.0

        opts = BacktestRunOptions(
            archive=Path(str(payload["archive"])),
            out_dir=out_dir,
            config_path=cfg_path,
            portfolio_sequencing=str(payload.get("portfolio_sequencing") or "single_market_only"),
            scheduling_mode=str(payload.get("scheduling_mode") or "coarse_bar"),
            fidelity_tier=str(payload.get("tier") or "A"),
            l2_archive=Path(str(payload["l2_archive"])) if payload.get("l2_archive") else None,
            fee_bps=fee_bps,
            simulate_risk_caps=bool(payload.get("simulate_risk_caps")),
        )

        self._jobs[job_id] = {"status": "queued", "created_at": time.time(), "user": uid}
        asyncio.create_task(self._finalize_job(job_id, opts))
        return web.json_response({"job_id": job_id, "status": "queued"}, status=202)

    async def _finalize_job(self, job_id: str, opts: BacktestRunOptions) -> None:
        loop = asyncio.get_running_loop()
        self._jobs[job_id]["status"] = "running"

        def _work() -> dict[str, Any]:
            opts.out_dir.mkdir(parents=True, exist_ok=True)
            return run_backtest(opts)

        try:
            summary = await loop.run_in_executor(self._executor, _work)
            self._jobs[job_id]["status"] = "done"
            self._jobs[job_id]["summary"] = summary
        except Exception as exc:
            self._jobs[job_id]["status"] = "error"
            self._jobs[job_id]["error"] = str(exc)
        finally:
            async with self._lock:
                self._running = max(0, self._running - 1)

    async def _job_get(self, request: web.Request) -> web.Response:
        jid = request.match_info["job_id"]
        j = self._jobs.get(jid)
        if j is None:
            return web.json_response({"error": "not_found"}, status=404)
        return web.json_response(j)
