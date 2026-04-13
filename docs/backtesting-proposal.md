# Backtesting — detailed plan

This document is the **implementation-oriented plan** for backtesting the Nothing Ever Happens / Polymarket bot: **what to measure**, **what data to use**, **archive vs live API**, **Polymarket limits**, and **optional dashboard hooks** for job orchestration.

It remains a **plan** until built; top-level section numbers are stable for review.

---

## Executive summary

| Decision | Choice |
| --- | --- |
| **Primary historical signal** | Polymarket CLOB **`GET /prices-history`** per **NO `token_id`**, stored locally after bulk ingest. |
| **Core per-market question** | **Earliest time \(t\)** at which **your entry predicate** (from `NothingHappensConfig` + spread model) is true on the cached price path — **not** a fixed “first minute” or “first 15s” window. |
| **Trades tape** | **Supplementary** (validation, volume research) — **not** the primary series for “when would **our** bot fire?” |
| **Settings / UI interaction** | **Recompute locally** against the archive when dials change; **do not** re-fetch a year of history per tweak. |
| **Network guardrails** | **Rate limits + quotas** on any code path that still hits Polymarket (cache miss, refresh, universe extend). |
| **Fidelity v1** | **Tier A** (price history + synthetic ask / spread); **Tier B** optional (vendor 1m L2). Tier A carries a **measured** `p` vs live-book bias — see §2.4. |

---

## 1. Goals and non-goals

### 1.1 Goals

| ID | Goal | Success signal |
| --- | --- | --- |
| G1 | **Parameter sensitivity** | Same universe, two configs → comparable metrics (entries, rough PnL, time-to-first-entry distribution). |
| G2 | **First executable moment** | For each market, report **`t_first`** = min time predicate holds (subject to discretization policy in §5). |
| G3 | **Resolution PnL** | Binary payoff for simulated NO hold to resolution when outcome known. |
| G4 | **Fast UX** | Dashboard / CLI backtest completes in **seconds** after cache warm (not proportional to re-downloading a year). |
| G5 | **Traceable runs** | Every run exports **fidelity tier**, **spread model version**, **universe manifest hash**, **sequencing mode**, **`t_open` policy**, and **sim parity flags** (§5.5–5.6). |

### 1.2 Non-goals (v1)

- Guaranteed parity with **live** fills (no hidden liquidity, no queue position) unless a **named sim mode** explicitly targets it.
- **Dynamic discovery replay** (“exactly what Gamma would have returned each day last year”) without frozen universe or separate snapshot infra.

---

## 2. Definitions

### 2.1 “First window when a trade would execute”

**Not** defined as calendar “first minute of listing” or “first 15 seconds.”

**Defined as:**

> Let \(P(t)\) be the **executable price proxy** for the NO leg at time \(t\) (from archived series + spread model). Let \(\text{Predicate}(P, \text{cfg})\) encode **max entry price**, **slippage / submitted price rule**, **min notional / min shares** (using tick metadata if available). Then  
> **`t_first = \min \{ t \in \mathcal{T} : \text{Predicate}(P(t), \text{cfg}) \}`**  
> where \(\mathcal{T}\) is the set of **evaluation times** (see §5.2).

If the predicate never holds, **`t_first = \emptyset`** (no simulated entry).

### 2.2 Price path vs trades path

| Source | What it is | Use |
| --- | --- | --- |
| **`prices-history`** | `{t, p}` series per **token id** | **Primary** path for \(P(t)\) proxy across full market life. |
| **Data API / on-chain trades** | Discrete fills by **anyone** | **Secondary** — “did the market trade near our threshold?” not “would **we** have passed risk + limit logic at \(t\)?” |

### 2.3 Fidelity tiers (unchanged names, sharper text)

| Tier | Input | Predicate uses | Limitation |
| --- | --- | --- | --- |
| **A** | `prices-history` + optional tick/min size from Gamma snapshot | Synthetic NO ask from \(p\) + model | Not true L2 depth; **`p` is not a guaranteed NO best ask** — see §2.4. |
| **B** | Minute L2 archive (e.g. PolymarketData) or self-snapshotted books | Walk ask ladder for size | Paid / heavier ingest. |
| **C** | Full matching model | Research | Out of scope v1. |

### 2.4 Price semantics, calibration, and error bands (Tier A)

**Risk:** `p` from `/prices-history` may systematically differ from the live **NO best ask** (mid vs last trade vs leg mix-ups, stale bars). That biases **`t_first`**, fill price, and PnL.

**Mitigations (required engineering):**

1. **Phase-0 calibration study** — For a fixed sample of markets and timestamps, compare `p` at the nearest history bar to **`GET /book`** (or documented best-ask fields) on the **same NO `token_id`**. Record mean/median error, percentiles, and max abs error; attach to ingest run metadata as `tier_a_calibration_stats` (JSON).
2. **Manifest + reports** — Store **`history_p_semantics_note`** (API doc link + date captured). Every `summary.json` includes **`fidelity_tier`** and **`calibration_run_id`** (or `uncalibrated`).
3. **Tier B or forward book capture** — Any workflow marketed internally as **execution-accurate** must use Tier B or a self-built book archive from `t_open`; Tier A results stay labeled **indicative** in machine-readable metadata only (`execution_fidelity: indicative`).

---

## 3. Polymarket API — rate limits and cost (planning numbers)

**Source:** [Polymarket rate limits](https://docs.polymarket.com/api-reference/rate-limits) (verify periodically; values can change).

### 3.1 Limits relevant to ingestion

| Bucket | Documented limit | Notes |
| --- | --- | --- |
| **`GET /prices-history`** | **1,000 requests / 10 s** | Per-endpoint sliding window. |
| **CLOB general** | **9,000 requests / 10 s** | Shared across CLOB endpoints — ingestion jobs must account for **other** calls (`/book`, Gamma, etc.). |
| **Enforcement style** | Cloudflare **throttle / queue** | Over limit → slowdown, not always clean **429**; jobs must **measure** latency under load and **stay under** limits with margin. |

**Rough capacity:** ~100 `/prices-history` calls per second **sustained** if you dedicated the whole CLOB budget to that endpoint — in practice share with retries and other traffic; **plan for ~50–200 req/s effective** only after measurement.

### 3.2 Cost

- **`/prices-history`** is documented as **public** (no API key in OpenAPI for that operation): **[docs](https://docs.polymarket.com/developers/CLOB/timeseries)**.
- **Dollar cost to Polymarket:** **$0** for documented public reads.
- **Your costs:** compute, storage, egress from your infra, optional **paid third-party** datasets, and **engineering time** if you exceed limits and need backoff/retry logic.

### 3.3 Known data caveats (operations)

- Some **closed** or migrated markets return **empty** `history` — handle as **missing**; do not assume universal coverage. See e.g. community reports in [py-clob-client#189](https://github.com/Polymarket/py-clob-client/issues/189).
- **`fidelity`** is described in **minutes** — coarser than “tick”; aligns with Tier A honesty.

---

## 4. Recommended strategy: archive-first + local recompute + guardrails

### 4.1 Why not “rate-limit only” on dial changes?

If every backtest parameter change **re-hit** Polymarket for **N markets × full date range**, you get:

- **Latency** proportional to **N** and network.
- **Throttle risk** even within 1k/10s (large **N** or parallel jobs).
- **Non-reproducible** runs if API responses shift slightly.

**Conclusion:** **Respectable rate limits are mandatory** on any network path, but **insufficient** as the **primary** backtest architecture.

### 4.2 Why not “one year of trades” as the core archive?

**Trades** answer “when did **someone** trade at price X?” They do **not** directly encode **resting** NO ask at every instant or **your** composite predicate (cash, caps, ETA, recovery).  

**Conclusion:** Archive **`prices-history`** (and optionally Tier B L2). Archive **trades** only if you add **explicit** research features (tape validation, volume).

### 4.3 Target architecture (three layers)

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 — Durable archive (Parquet/SQLite/object store)     │
│  • universe manifest + per-token price series + resolutions    │
│  • versioned ingest run id + content hashes + coverage flags  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2 — Local backtest engine                             │
│  • load series → compute t_first / fills / PnL per cfg       │
│  • no HTTP in hot loop (config flag ENFORCE_LOCAL_ONLY)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3 — Network façade (strict quotas)                    │
│  • ingest job, “refresh market”, “extend window”             │
│  • per-user / global token bucket; max concurrent fetches    │
│  • single global ingest lock + queue (§7.4)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Time discretization and “first hit” algorithm

### 5.1 Evaluation grid \(\mathcal{T}\)

Choose **one** policy per run (record in `run_manifest.json`):

| Policy | \(\mathcal{T}\) | Pros | Cons |
| --- | --- | --- | --- |
| **P1 — Data-native** | Every timestamp \(t_i\) present in cached `prices-history` | Simple, no extra assumptions | Spacing uneven; may miss between samples. |
| **P2 — Poll-aligned** | Resample or nearest-neighbor to **`price_poll_interval_sec`** from documented **`t_open`** (§6.1) | Closer to live bot sampling | Requires frozen **`t_open`**; may undersample if history coarser than poll. |
| **P3 — Hybrid** | P1 for “first hit” scan; optional P2 for reporting | Balance | More code. |

**Recommendation:** **P1** for v1 implementation speed; **P2** as optional `--align-to-poll` for fidelity experiments.

### 5.2 Predicate \(\text{Predicate}(P, \text{cfg})\) (Tier A sketch)

Align with production logic in `nothing_happens.py`:

1. **Executable NO ask proxy** — e.g. `no_ask = f(p, spread_model)` where `f` might be `p + half_spread` or “treat `p` as mid and add ticks.”
2. **In range** — `no_ask > 0` and `no_ask <= max_entry_price` (or submitted price rule using `allowed_slippage` and `_submitted_buy_price` equivalent).
3. **Sizing** — `target_notional` from cash model; require `target_notional / no_ask >= min_shares_effective` if simulating size skip.

Document **`spread_model`** version in run metadata.

### 5.3 Shared fill / slippage / price-cap logic (code parity)

**Risk:** Duplicated logic between sim and `place_market_order` drifts → endless “sim vs live” bugs.

**Mitigations:**

1. **Single pure function** (or small module) used by both the backtest engine **and** unit tests that assert parity with **`MarketOrderIntent`** + `allowed_slippage` + `price_cap` behavior in `nothing_happens` / `polymarket_clob.py`.
2. **Golden vectors** — Table-driven tests: inputs `(no_ask, cfg)` → expected submitted clamp and fill accept/reject.
3. **CI** — Runs those tests **network-off**.

### 5.4 Live-only paths: balance recovery and order errors

**Risk:** Live **`_recover_balance_fill`** can record a position when the REST path errored but conditional balance shows shares; a naive sim never models this → systematic divergence.

**Mitigations:**

1. **`sim_balance_recovery: bool`** in run manifest (default **`false`** for v1). When `false`, `run_manifest.json` lists **`live_path_excluded: ["balance_recovery"]`**.
2. Optional **v2 mode** — If `true`, after a simulated “order error” draw, read a **synthetic** conditional balance from Tier B or from a **recorded** live ledger export (out of scope until data exists).

### 5.5 Pending entries, backoff, and poll cadence

**Risk:** Live uses **retry/backoff** and monotonic “next attempt” times; a naive per-bar scan does not match **when** the next evaluation happens relative to `t_first`.

**Mitigations:**

1. **`scheduling_mode`** in manifest: **`coarse_bar`** (evaluate only on history bars after `t_first` eligibility — fast, documented approximation) vs **`strategy_loop`** (reuse or mirror pending-entry scheduling rules from the real loop — higher fidelity, more code).
2. Default v1: **`coarse_bar`** with **`scheduling_mode`** explicit in output.

### 5.6 Multi-market portfolio ordering

**Risk:** Live uses **concurrent** work (`asyncio.gather`-style); a **serial** backtest changes who gets cash first → different entries and PnL.

**Mitigations:**

1. **`portfolio_sequencing`** required in every run: **`serial_by_slug`** | **`time_ordered_global`** (merge all markets’ \(\mathcal{T}\) into one timeline, tie-break by slug) | **`single_market_only`**.
2. **Default v1:** **`single_market_only`** enforced in CLI unless operator sets another mode (prevents silent wrong portfolio stats).
3. Document mapping to live: if you later add **`parallel_async`**, it must be **stochastic or seeded** (multiple runs) unless you capture a live event log.

### 5.7 Algorithm (single market, single config)

```
INPUT: sorted points [(t_i, p_i)], cfg, resolution outcome
OUTPUT: t_first or NONE, simulated entry price, PnL if entered

for each (t_i, p_i) in order:
    no_ask = spread_model(p_i, cfg)
    if not predicate(no_ask, cfg, wallet_state):
        continue
    t_first = t_i
    fill_price = shared_fill_rule(no_ask, cfg)  # §5.3
    update wallet_state
    break per market entry rule

at resolution: apply binary payoff to NO position
```

Multi-market: apply **`portfolio_sequencing`** (§5.6).

### 5.8 Drawdown and risk caps

**Risk:** Skipping drawdown hides kill-switch behavior; enabling it without mark-to-market is misleading.

**Mitigations:**

1. **`drawdown_mode`** in manifest: **`step_mtm`** (revalue open NO at each evaluation using history `p` + same spread model — **proxy** drawdown) | **`off`**.
2. When **`off`**, `run_manifest.json` includes **`drawdown_mode: off`** and **`risk_metrics_partial: true`** so downstream tools know DD stats are absent by choice.
3. **Exposure caps** from `NothingHappensConfig` / `RiskConfig` must either be simulated each step or listed under **`live_path_excluded`**.

---

## 6. Data model (archive schema)

### 6.1 Universe manifest (`universe.parquet` or `universe.jsonl`)

| Column | Type | Description |
| --- | --- | --- |
| `slug` | string | Human id |
| `no_token_id` | string | CLOB token id for NO outcome |
| `yes_token_id` | string optional | Cross-checks / YES history |
| `condition_id` | string | On-chain / Gamma id |
| **`t_open`** | int64 unix | **Frozen policy per manifest** — e.g. Gamma `startDate` **or** first `t` in `prices-history` **or** first CLOB listing time; pick **one** and set **`t_open_source`** on the manifest file. |
| **`t_open_source`** | string enum | `gamma_start` \| `first_history_bar` \| `clob_listing` \| … |
| `t_end` | int64 unix | Resolution / close horizon for ETA filters |
| **`outcome_no_wins`** | bool or enum | Resolved: did NO win? |
| **`resolution_status`** | string | `resolved` \| `void` \| `disputed` \| `unknown` — **void/disputed** markets use an explicit PnL rule (e.g. exclude from PnL sum, or mark `pnl=null` with reason). |
| **`gamma_snapshot_utc`** | string ISO | When outcomes / metadata were read (reproducibility). |
| `ingest_version` | string | Manifest schema version |
| **`coverage_class`** | string | `ok` \| `empty_history` \| `partial_range` \| `below_min_bars` |
| **`bar_count`** | int | Points ingested for NO token |
| **`min_bars_threshold`** | int optional | Ingest parameter for quality gate |

**Join validation:** On ingest, assert **`condition_id` + `slug`** consistency with Gamma row; reject or flag rows that fail.

### 6.2 Price series (`prices/{token_id}.parquet` or partitioned hive)

| Column | Type | Description |
| --- | --- | --- |
| `token_id` | string | NO token |
| `t` | int64 | Unix seconds (**validate** unit: reject if values look like ms — §6.4) |
| `p` | float | Price from API |
| `ingest_run_id` | string | Batch id |
| `source` | string | `clob_prices_history` |

**Primary key:** `(token_id, t)` deduplicated on ingest. **Invariant:** `t` strictly increasing per file after sort.

### 6.3 Ingest metadata table

| Field | Purpose |
| --- | --- |
| `ingest_run_id`, `started_at`, `completed_at` | Audit |
| `params` (JSON) | `startTs`, `endTs`, `interval`, `fidelity` used |
| `markets_requested`, `markets_ok`, `markets_empty`, `markets_partial` | Health |
| `tier_a_calibration_stats` | Optional link or embed from §2.4 |
| `error_log_uri` | Debugging |
| **`status`** | `complete` \| `partial` \| `failed` |

### 6.4 Archive validation (`backtest validate` command)

**Risk:** Partial/corrupt archives trusted by the runner.

**Mitigations — implement a **validate** subcommand** that:

1. Checks **manifest ↔ files** (every `no_token_id` has a series file when `coverage_class` expects it).
2. Asserts **monotonic `t`**, **no duplicate `(token_id,t)`**, and **reasonable unix range** (catches ms vs s).
3. Computes **min/max `t` per token** vs requested window; flags **`partial_range`**.
4. Emits **`validate_report.json`** with exit code non-zero if **hard** gates fail.

**Runner behavior:** `run` may accept `--require-validated-manifest` to refuse a stale or unvalidated ingest.

### 6.5 Survivorship and universe bias

**Risk:** Only including **resolved winners** or post-hoc liquid markets inflates measured edge.

**Mitigations:**

1. Manifest field **`universe_rule`** (text or enum): e.g. `all_listed_asof_YYYY-MM-DD`, `resolved_only`, `custom_sql`.
2. **`summary.json`** includes **`universe_rule`** and **count by `resolution_status`** so aggregates are comparable across runs.

---

## 7. Ingestion job specification

### 7.1 Phases of one ingest run

1. **Acquire global ingest lock** (§7.4) — refuse or queue second concurrent megajob.
2. **Load universe** → list of `(no_token_id, start_ts, end_ts)` per market (clamp to market life).
3. **Deduplicate** tokens if multiple slugs share token (rare; log).
4. **Fetch loop:**
   - Respect **global token bucket** (e.g. target ≤800 `/prices-history` per 10s to stay under 1k with jitter).
   - **Exponential backoff** on 5xx / obvious throttle; **jitter** on retries.
   - **Resume:** per-token checkpoint — skip tokens already complete for same **`ingest_params_hash`** unless `--force`.
5. **Write** Parquet **atomically** (temp file + rename).
6. **Record** manifest row counts, hashes, **`coverage_class`**, and **`status`**.

### 7.2 Query parameters (defaults for year-scale pull)

| Param | Suggested default | Note |
| --- | --- | --- |
| `market` | NO `token_id` | Required |
| `startTs` / `endTs` | Per market or global window | Narrow to reduce payload |
| `interval` | `max` or `all` then slice locally | Measure response size |
| `fidelity` | `1` (minute) unless API allows finer | Matches docs |

### 7.3 Idempotency and config identity

- **`ingest_params_hash = hash(canonical_json(token_id, startTs, endTs, interval, fidelity))`** — floats must be **quantized** or **stringified** in canonical form so hashes are stable.
- Re-run ingest: **no duplicate rows** (merge on `t`).

### 7.4 Global lock, checkpoint, disk, and Cloudflare

| Risk | Mitigation |
| --- | --- |
| Two ingests thrash API / corrupt writes | **Single global ingest lock** (file lock or DB); queued starts. |
| Job dies mid-run | **Per-token checkpoint** file or table row; resume from last complete token. |
| Disk exhaustion | **Pre-flight estimate** (tokens × observed bytes/sample); optional **`--max-gb`** abort. |
| Cloudflare slowdown (no 429) | **Metrics:** rolling req/s, latency p95; **adaptive throttle** to stay under measured ceiling. |

---

## 8. Backtest runner specification

### 8.1 Inputs

- **Archive path** (local or mounted).
- **`NothingHappensConfig`** (or diff from baseline for A/B) — serialized with **canonical JSON** for hashing.
- **Tier** (`A` | `B`).
- **Discretization policy** (P1/P2/P3).
- **`t_open` policy** — must match manifest’s **`t_open_source`** or runner errors.
- **Initial cash** (float).
- **`portfolio_sequencing`** (§5.6).
- **`scheduling_mode`** (§5.5).
- **`drawdown_mode`** (§5.8).
- **`sim_balance_recovery`** (§5.4).

### 8.2 Outputs

| Artifact | Format |
| --- | --- |
| `summary.json` | Aggregates: markets scanned, **entries**, **excluded_empty**, **excluded_partial**, win rate, total PnL, max DD (if mode on), **`universe_rule`**, fidelity metadata |
| `per_market.parquet` | `slug`, `t_first`, `entered`, `fill_price`, `pnl`, `reason_skip`, `coverage_class` |
| `equity_curve.csv` | Optional if multi-step portfolio sim |
| `run_manifest.json` | Config hash, archive hash, git commit, tier, **sequencing**, **scheduling_mode**, **drawdown_mode**, **`live_path_excluded`**, **`execution_fidelity`** |

### 8.3 Quality gates (empty / sparse history)

**Risk:** Silent drop of most universe → misleading aggregates.

**Mitigations:**

1. **`--min-markets-with-data`** and **`--min-bars-per-market`** — abort if unmet.
2. **`summary.json`** always includes **`markets_total`**, **`markets_with_entry`**, **`markets_skipped_reason_counts`**.

### 8.4 CLI (implemented — v1)

**Universe file for ingest:** JSONL, one object per line. Required: **`no_token_id`** (NO CLOB token id). Optional: `slug`, `start_ts`, `end_ts`, `t_open`, `t_open_source`, `t_end`, `outcome_no_wins`, `resolution_status`, `condition_id`, `min_order_size`, `gamma_snapshot_utc`.

```text
python -m bot.backtest ingest --archive ./var/backtest/demo --universe ./universe.jsonl
```

```text
python -m bot.backtest validate --archive ./var/backtest/demo
```

```text
python -m bot.backtest run \
  --archive ./var/backtest/demo \
  --config-json ./backtest_cfg.json \
  --initial-cash 10000 \
  --out ./runs/run_001
```

(`run` reads **`universe.parquet`** inside the archive produced by **`ingest`**; `--tier` / `--portfolio-sequencing` flags are expressed in **`run_manifest.json`** for this v1.)

### 8.5 Dashboard integration (later)

- **POST /api/backtest** accepts **config diff** + **dataset id** → returns **job id**.
- Worker reads **only archive**; **never** loops Polymarket per slider tick.
- **Global limit:** e.g. **N concurrent jobs**, **M runs per user per hour**.
- **`ENFORCE_LOCAL_ONLY=1`** in deployment: network fallback **disabled** (no accidental hammering).

---

## 9. Rate limiting and quotas (application layer)

Even with an archive, some routes hit the network. Define **hard caps**:

| Route | Suggested cap | Purpose |
| --- | --- | --- |
| `ingest.start` | 1 global + queue | Avoid parallel megajobs |
| `ingest.token` | ≤800 req/10s internal throttle | Stay under Polymarket 1k/10s |
| `cache.refresh_market` | e.g. 10/min per user | Keep refresh from dominating CLOB budget |
| `backtest.run` (network fallback) | **0** when `ENFORCE_LOCAL_ONLY` | Deterministic local runs |

Expose **`429`** with **`Retry-After`** from app when internal quota exceeded.

---

## 10. Third-party and indexers (short)

| Class | Examples | Historical NO book for backtest? |
| --- | --- | --- |
| **Vendor L2** | [PolymarketData](https://www.polymarketdata.co/polymarket-order-book-data) (1m) | **Tier B** — minute snapshots, not sub-minute. |
| **On-chain indexers** | Goldsky, The Graph, Envio, Dune | **Trades / settlement**, not off-chain CLOB resting book. |
| **Forward capture** | CLOB WebSocket `book` / `best_bid_ask` | **Build your own** archive from `t_open` for sub-minute **going forward**. |

---

## 11. Phased delivery (detailed)

### Phase 0 — Spike (time-boxed)

| Task | Output |
| --- | --- |
| Fetch `prices-history` for 5 known NO tokens | Script in `scripts/` |
| **Calibration** — document `{t,p}` vs live `/book` NO best ask (§2.4) | JSON stats + short appendix in repo |
| Implement `spread_model_v0` | Constant half-tick |
| Compute `t_first` on paper for 1 config | Notebook or unit test |
| **Clock check** — confirm `t` is seconds | Assert in spike |

**Exit:** Go/no-go on Tier A **with recorded bias stats**; else Tier B scope.

### Phase 1 — Archive + local scan

| Task | Output |
| --- | --- |
| Parquet writers + manifest (with **`coverage_class`**, **`t_open_source`**) | `bot/backtest/` module |
| Ingest CLI with throttle + checkpoint + lock | `scripts/backtest_ingest.py` |
| **`validate`** command (§6.4) | `bot/backtest/validate.py` |
| Pure function `first_executable_moment(series, cfg)` + **§5.3 shared fill** | Tested |
| Golden-file test on 3 markets + **network-off CI** | CI |
| **Acceptance:** hand-checked **`t_first`** for ≥1 market on P1 and P2 | Doc table in test data README |

**Exit:** One-command ingest + validate + offline report; quality gates enforced.

### Phase 2 — Portfolio + parity knobs

| Task | Output |
| --- | --- |
| **`portfolio_sequencing`** modes (§5.6) | Config flags |
| Map ETA / max position caps or list under **`live_path_excluded`** | Manifest |
| Resolution PnL with **`resolution_status`** (void/disputed) | Join + tests |
| Optional **`scheduling_mode=strategy_loop`** spike | If needed |

**Exit:** Summary metrics on fixture universe; multi-market only in **`time_ordered_global`** or documented mode.

### Phase 3 — Dashboard + quotas

| Task | Output |
| --- | --- |
| Job queue + results UI | Admin or dedicated page |
| User / global quotas | Middleware |
| Dataset versioning in UI | Dropdown |

**Exit:** A/B on cached year from UI without per-tick network.

### Phase 4 — Tier B adapter (optional)

| Task | Output |
| --- | --- |
| PolymarketData (or chosen vendor) client | Pluggable `HistoricalExchange` |
| Comparison report Tier A vs B | `compare.html` or notebook |

---

## 12. Engineering risks and mitigations (checklist)

| # | Risk | Mitigation (where defined) |
| --- | --- | --- |
| 1 | `p` ≠ live NO best ask | §2.4 calibration; Tier B for execution-grade; `execution_fidelity` in manifest |
| 2 | Empty / partial history | `coverage_class`, §8.3 gates, `markets_skipped_reason_counts` |
| 3 | Ambiguous `t_open` | §6.1 `t_open` + `t_open_source`; runner must match; Phase 1 golden tests |
| 4 | Multi-market cash ordering | §5.6 `portfolio_sequencing`; default `single_market_only` |
| 5 | Drawdown / kill-switch blind spots | §5.8 `drawdown_mode` + `risk_metrics_partial` |
| 6 | Slippage / price-cap drift | §5.3 shared pure function + golden vectors |
| 7 | Balance recovery divergence | §5.4 `sim_balance_recovery` + `live_path_excluded` |
| 8 | Pending / backoff vs coarse bars | §5.5 `scheduling_mode` |
| 9 | Ingest scale / thundering herd | §7.4 lock, checkpoint, adaptive throttle |
| 10 | Partial corrupt archive | §6.4 validate; `--require-validated-manifest` |
| 11 | Resolution join wrong | §6.1 join validation + `resolution_status` |
| 12 | Survivorship bias | §6.5 `universe_rule` + counts by status |
| 13 | Config hash instability | §7.3 canonical JSON + float policy |
| 14 | ms vs s time bugs | §6.2, §6.4 validation |
| 15 | Dashboard / shared host abuse | §8.5 `ENFORCE_LOCAL_ONLY`, §9 quotas, job timeouts |
| 16 | Weak acceptance criteria | §11 Phase 0–1 exit criteria + hand-checked `t_first` |

---

## 13. Open decisions (residual checklist)

- [ ] **Default `t_open_source`** — pick `gamma_start` vs `first_history_bar` for first shipped manifest (then freeze).
- [ ] **Fees** — include category fee table in PnL or `live_path_excluded: ["fees"]`.
- [ ] **neg-risk / multi-outcome** — explicitly excluded or flagged in manifest.

---

## 14. References

- [CLOB `prices-history` / timeseries](https://docs.polymarket.com/developers/CLOB/timeseries)  
- [Polymarket rate limits](https://docs.polymarket.com/api-reference/rate-limits)  
- [CLOB order book (live)](https://docs.polymarket.com/trading/orderbook)  
- Example vendor L2: [PolymarketData](https://www.polymarketdata.co/polymarket-order-book-data)  

---

## 15. Document history

| Date | Change |
| --- | --- |
| Initial | High-level proposal |
| 2026-04-13 | Expanded: first-executable definition, archive-first vs dial API, rate limits, schema, ingest/backtest specs, quotas, phased tasks |
| 2026-04-13 | Risk mitigations: calibration, coverage gates, `t_open` freeze, sequencing modes, shared fill, recovery/scheduling/DD flags, validate command, survivorship, parity matrix, removed non-engineering/legal framing |
| 2026-04-13 | **Implementation v1:** `python -m bot.backtest` (`ingest`, `validate`, `run`), `bot/order_math.py`, `pytest.ini` `pythonpath` |
