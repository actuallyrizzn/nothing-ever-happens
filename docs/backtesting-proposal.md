# Backtesting — detailed plan

This document is the **implementation-oriented plan** for backtesting the Nothing Ever Happens / Polymarket bot. It incorporates product decisions from design discussion: **what to measure**, **what data to use**, **archive vs live API**, **Polymarket limits**, and **how the dashboard should behave**.

It remains a **plan** until built; section numbers are stable for review.

---

## Executive summary

| Decision | Choice |
| --- | --- |
| **Primary historical signal** | Polymarket CLOB **`GET /prices-history`** per **NO `token_id`**, stored locally after bulk ingest. |
| **Core per-market question** | **Earliest time \(t\)** at which **your entry predicate** (from `NothingHappensConfig` + spread model) is true on the cached price path — **not** a fixed “first minute” or “first 15s” window. |
| **Trades tape** | **Supplementary** (validation, volume research) — **not** the primary series for “when would **our** bot fire?” |
| **Settings / UI interaction** | **Recompute locally** against the archive when users change dials; **do not** re-fetch a year of history per tweak. |
| **Network guardrails** | **Rate limits + quotas** on any code path that still hits Polymarket (cache miss, refresh, universe extend). |
| **Fidelity v1** | **Tier A** (price history + synthetic ask / spread); **Tier B** optional (vendor 1m L2). |

---

## 1. Goals and non-goals

### 1.1 Goals

| ID | Goal | Success signal |
| --- | --- | --- |
| G1 | **Parameter sensitivity** | Same universe, two configs → comparable metrics (entries, rough PnL, time-to-first-entry distribution). |
| G2 | **First executable moment** | For each market, report **`t_first`** = min time predicate holds (subject to discretization policy in §5). |
| G3 | **Resolution PnL** | Binary payoff for simulated NO hold to resolution when outcome known. |
| G4 | **Fast UX** | Dashboard / CLI backtest completes in **seconds** after cache warm (not proportional to re-downloading a year). |
| G5 | **Honest reporting** | Every run exports **fidelity tier**, **spread model version**, **universe manifest hash**. |

### 1.2 Non-goals (v1)

- Guaranteed parity with **live** fills (no hidden liquidity, no queue position).
- **Dynamic discovery replay** (“exactly what Gamma would have returned each day last year”) without frozen universe or separate snapshot infra.
- Regulatory / tax-grade “verified” returns.

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
| **A** | `prices-history` + optional tick/min size from Gamma snapshot | Synthetic NO ask from \(p\) + model | Not true L2 depth. |
| **B** | Minute L2 archive (e.g. PolymarketData) or self-snapshotted books | Walk ask ladder for size | Paid / heavier ingest. |
| **C** | Full matching model | Research | Out of scope v1. |

---

## 3. Polymarket API — rate limits and cost (planning numbers)

**Source:** [Polymarket rate limits](https://docs.polymarket.com/api-reference/rate-limits) (verify periodically; values can change).

### 3.1 Limits relevant to ingestion

| Bucket | Documented limit | Notes |
| --- | --- | --- |
| **`GET /prices-history`** | **1,000 requests / 10 s** | Per-endpoint sliding window. |
| **CLOB general** | **9,000 requests / 10 s** | Shared across CLOB endpoints — ingestion jobs must account for **other** calls (`/book`, Gamma, etc.). |
| **Enforcement style** | Cloudflare **throttle / queue** | Over limit → slowdown, not always clean 429; design jobs to **stay under** limits. |

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
- **Throttle risk** even within 1k/10s (large **N** or parallel users).
- **Non-reproducible** runs if API responses shift slightly.

**Conclusion:** **Respectable rate limits are mandatory** on any network path, but **insufficient** as the **primary** backtest architecture.

### 4.2 Why not “one year of trades” as the core archive?

**Trades** answer “when did **someone** trade at price X?” They do **not** directly encode **resting** NO ask at every instant or **your** composite predicate (cash, caps, ETA, recovery).  

**Conclusion:** Archive **`prices-history`** (and optionally Tier B L2). Archive **trades** only if you add **explicit** research features (tape validation, volume).

### 4.3 Target architecture (three layers)

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 — Durable archive (Parquet/SQLite/object store)     │
│  • universe manifest + per-token price series + resolutions  │
│  • versioned ingest run id + content hashes                 │
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
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Time discretization and “first hit” algorithm

### 5.1 Evaluation grid \(\mathcal{T}\)

Choose **one** policy (product decision):

| Policy | \(\mathcal{T}\) | Pros | Cons |
| --- | --- | --- | --- |
| **P1 — Data-native** | Every timestamp \(t_i\) present in cached `prices-history` | Simple, no extra assumptions | Spacing uneven; may miss between samples. |
| **P2 — Poll-aligned** | Resample or nearest-neighbor to **`price_poll_interval_sec`** from configurable **`t_listing`** | Closer to live bot sampling | Requires defining **`t_listing`**; may undersample if history coarser than poll. |
| **P3 — Hybrid** | P1 for “first hit” scan; optional P2 for reporting | Balance | More code. |

**Recommendation:** **P1** for v1 implementation speed; **P2** as optional `--align-to-poll` for fidelity experiments.

### 5.2 Predicate \(\text{Predicate}(P, \text{cfg})\) (Tier A sketch)

Align with production logic in `nothing_happens.py`:

1. **Executable NO ask proxy** — e.g. `no_ask = f(p, spread_model)` where `f` might be `p + half_spread` or “treat `p` as mid and add ticks.”
2. **In range** — `no_ask > 0` and `no_ask <= max_entry_price` (or submitted price rule using `allowed_slippage` and `_submitted_buy_price` equivalent).
3. **Sizing** — `target_notional` from cash model; require `target_notional / no_ask >= min_shares_effective` if simulating size skip.

Document **`spread_model`** version in run metadata.

### 5.3 Algorithm (single market, single config)

```
INPUT: sorted points [(t_i, p_i)], cfg, resolution outcome
OUTPUT: t_first or NONE, simulated entry price, PnL if entered

for each (t_i, p_i) in order:
    no_ask = spread_model(p_i, cfg)
    if not predicate(no_ask, cfg, wallet_state):
        continue
    t_first = t_i
    simulate fill at no_ask (or submitted price rule)
    update wallet_state
    break outer loops per market entry rule

at resolution: apply binary payoff to NO position
```

Multi-market v2 adds **portfolio sequencing** (same timestamps across markets or priority order — match live **async gather** behavior or document simplified **serial** mode).

---

## 6. Data model (archive schema)

### 6.1 Universe manifest (`universe.parquet` or `universe.jsonl`)

| Column | Type | Description |
| --- | --- | --- |
| `slug` | string | Human id |
| `no_token_id` | string | CLOB token id for NO outcome |
| `yes_token_id` | string optional | If needed for cross-checks |
| `condition_id` | string | On-chain / Gamma id |
| `t_open` | int64 unix | **Definition documented** — e.g. Gamma `start` or first history point |
| `t_end` | int64 unix | Resolution / close horizon for ETA filters |
| `outcome_no_wins` | bool or enum | Resolved: did NO win? (from Gamma / curated) |
| `ingest_version` | string | Manifest schema version |

### 6.2 Price series (`prices/{token_id}.parquet` or partitioned hive)

| Column | Type | Description |
| --- | --- | --- |
| `token_id` | string | NO token |
| `t` | int64 | Unix seconds (match API) |
| `p` | float | Price from API |
| `ingest_run_id` | string | Batch id |
| `source` | string | `clob_prices_history` |

**Primary key:** `(token_id, t)` deduplicated on ingest.

### 6.3 Ingest metadata table

| Field | Purpose |
| --- | --- |
| `ingest_run_id`, `started_at`, `completed_at` | Audit |
| `params` (JSON) | `startTs`, `endTs`, `interval`, `fidelity` used |
| `markets_requested`, `markets_ok`, `markets_empty` | Health |
| `error_log_uri` | Debugging |

---

## 7. Ingestion job specification

### 7.1 Phases of one ingest run

1. **Load universe** → list of `(no_token_id, start_ts, end_ts)` per market (clamp to market life).
2. **Deduplicate** tokens if multiple slugs share token (rare; log).
3. **Fetch loop:**
   - Respect **global token bucket** (e.g. target ≤800 `/prices-history` per 10s to stay under 1k with jitter).
   - **Exponential backoff** on 5xx / obvious throttle.
   - **Resume:** skip tokens already in archive with same `(ingest_params_hash)` unless `--force`.
4. **Write** Parquet atomically (temp file + rename).
5. **Record** manifest row counts and hashes.

### 7.2 Query parameters (defaults for year-scale pull)

| Param | Suggested default | Note |
| --- | --- | --- |
| `market` | NO `token_id` | Required |
| `startTs` / `endTs` | Per market or global window | Narrow to reduce payload |
| `interval` | `max` or `all` then slice locally | Measure response size |
| `fidelity` | `1` (minute) unless API allows finer | Matches docs |

### 7.3 Idempotency

- **`ingest_params_hash = hash(token_id, startTs, endTs, interval, fidelity)`** stored per series file.
- Re-run ingest: **no duplicate rows** (merge on `t`).

---

## 8. Backtest runner specification

### 8.1 Inputs

- **Archive path** (local or mounted).
- **`NothingHappensConfig`** (or diff from baseline for A/B).
- **Tier** (`A` | `B`).
- **Discretization policy** (P1/P2/P3).
- **Initial cash** (float).
- **RiskConfig** subset (exposure caps; drawdown optional off in v1).

### 8.2 Outputs

| Artifact | Format |
| --- | --- |
| `summary.json` | Aggregates: markets scanned, entries, win rate, total PnL proxy, max DD |
| `per_market.parquet` | `slug`, `t_first`, `entered`, `fill_price`, `pnl`, `reason_skip` |
| `equity_curve.csv` | Optional if multi-step portfolio sim |
| `run_manifest.json` | Config hash, archive hash, git commit, tier |

### 8.3 CLI (illustrative)

```text
python -m bot.backtest run \
  --archive ./var/backtest/v2026-04 \
  --universe ./universe.parquet \
  --config-json ./backtest_cfg.json \
  --tier A \
  --out ./runs/run_001
```

### 8.4 Dashboard integration (later)

- **POST /api/backtest** accepts **config diff** + **dataset id** → returns **job id**.
- Worker reads **only archive**; **never** loops Polymarket per slider tick.
- **Global limit:** e.g. **N concurrent jobs**, **M runs per user per hour**.

---

## 9. Rate limiting and quotas (application layer)

Even with an archive, some routes hit the network. Define **hard caps**:

| Route | Suggested cap | Purpose |
| --- | --- | --- |
| `ingest.start` | 1 global + queue | Avoid parallel megajobs |
| `ingest.token` | ≤800 req/10s internal throttle | Stay under Polymarket 1k/10s |
| `cache.refresh_market` | e.g. 10/min per user | Abuse prevention |
| `backtest.run` (network fallback) | **0** in prod v1 | Force local-only |

Expose **`429`** with **`Retry-After`** from app when user triggers too many refresh operations.

---

## 10. Third-party and indexers (short)

| Class | Examples | Historical NO book for backtest? |
| --- | --- | --- |
| **Vendor L2** | [PolymarketData](https://www.polymarketdata.co/polymarket-order-book-data) (1m) | **Tier B** — minute snapshots, not sub-minute. |
| **On-chain indexers** | Goldsky, The Graph, Envio, Dune | **Trades / settlement**, not off-chain CLOB resting book. |
| **Forward capture** | CLOB WebSocket `book` / `best_bid_ask` | **Build your own** archive from `t_open` if product needs sub-minute **going forward**. |

---

## 11. Phased delivery (detailed)

### Phase 0 — Spike (time-boxed)

| Task | Output |
| --- | --- |
| Fetch `prices-history` for 5 known NO tokens | Script in `scripts/` |
| Document `{t,p}` vs live `/book` best ask | Markdown appendix |
| Implement `spread_model_v0` | Constant half-tick |
| Compute `t_first` on paper for 1 config | Notebook or unit test |

**Exit:** Go/no-go on Tier A credibility.

### Phase 1 — Archive + local scan

| Task | Output |
| --- | --- |
| Parquet writers + manifest | `bot/backtest/` module |
| Ingest CLI with throttle | `scripts/backtest_ingest.py` |
| Pure function `first_executable_moment(series, cfg)` | Tested |
| Golden-file test on 3 markets | CI |

**Exit:** One-command ingest + one-command report offline.

### Phase 2 — Portfolio + parity knobs

| Task | Output |
| --- | --- |
| Multi-market serial or documented parallel policy | Config flag |
| Map ETA / max position caps | Match `NothingHappensConfig` fields |
| Resolution PnL | Gamma outcome join |

**Exit:** Summary metrics within sanity bounds on fixture universe.

### Phase 3 — Dashboard + quotas

| Task | Output |
| --- | --- |
| Job queue + results UI | Admin or dedicated page |
| User / global quotas | Middleware |
| Dataset versioning in UI | Dropdown |

**Exit:** Non-engineer can run A/B on cached year.

### Phase 4 — Tier B adapter (optional)

| Task | Output |
| --- | --- |
| PolymarketData (or chosen vendor) client | Pluggable `HistoricalExchange` |
| Comparison report Tier A vs B | `compare.html` |

---

## 12. Risks (expanded)

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Empty `prices-history` | Missing markets | Manifest `markets_empty`; exclude from metrics; optional imputation **off** |
| Lookahead in universe | Inflated edge | Frozen manifest at research date; document |
| `p` ≠ tradable NO ask | Wrong `t_first` | Tier B or calibration sweep; disclose Tier A assumption |
| Ingest job failure mid-run | Partial archive | Resume tokens; manifest `status=partial` |
| User expects live parity | Trust loss | Run banner: tier + spread model version |

---

## 13. Open decisions (checklist)

- [ ] **`t_open` definition** — Gamma field vs first price point.
- [ ] **Portfolio cross-market ordering** — serial vs parallel vs simplified.
- [ ] **Fees** — include category fee table or ignore in v1.
- [ ] **neg-risk / multi-outcome** — explicitly excluded or flagged.

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
