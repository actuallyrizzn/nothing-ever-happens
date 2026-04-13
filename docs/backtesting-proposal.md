# Backtesting — proposed plan

This document proposes how to add **backtesting** to the Nothing Ever Happens / Polymarket bot: goals, constraints from the current codebase, data that exists on Polymarket’s side, fidelity tiers, architecture sketch, phases, and risks. It is a **plan only**; no implementation is implied.

---

## 1. Goals (what “backtesting” should answer)

| Goal | Description |
| --- | --- |
| **Parameter sensitivity** | Compare `NothingHappensConfig` (max entry, slippage, cash %, ETA windows, poll intervals, caps) on the **same historical path** without live capital. |
| **Regime behavior** | See how often the strategy would have entered, hit risk limits, or idled under different market conditions. |
| **Regression safety** | After code changes, re-run a fixed scenario and diff metrics (trade count, PnL proxy, max “exposure” path). |
| **Honest limits** | Report **fidelity level** (midpoint vs L2-replay) so results are not mistaken for guaranteed live performance. |

Non-goals for an initial release:

- Regulatory or tax reporting (“verified” backtested returns).
- Sub-second HFT-style simulation without external L2 archives.

---

## 2. Current system — what we have today

### 2.1 Live and paper runtimes

- **`NothingHappensRuntime`** (`bot/strategy/nothing_happens.py`) drives discovery, eligibility, price cycles, pending entries, dispatch, and risk hooks. It is **async**, **multi-market**, and tightly coupled to **wall clock** (`time.time()`, asyncio loop time, `ThreadPoolExecutor` for blocking CLOB calls).
- **`PaperExchangeClient`** (`bot/exchange/paper.py`) simulates fills using a **configurable mid** and synthetic tight book — it does **not** replay history; it is unsuitable as a backtest engine by itself.
- **`PolymarketClobExchangeClient`** hits real **`/book`**, orders, balances — correct for live/paper-forward tests, not for historical replay without substitution.

### 2.2 Decisions that need historical inputs

The strategy’s entry path (simplified):

1. **Universe** — `fetch_candidate_markets` / Gamma-derived standalone markets (binary NO, filters, ETA bounds, `max_end_date_months`).
2. **Per eligible market** — `get_order_book(no_token_id)` → **best ask** on NO vs `max_entry_price` and slippage logic (`_submitted_buy_price`, `_build_entry_plan`).
3. **Sizing** — cash %, min/fixed USD, min shares vs book rules.
4. **Risk** — `RiskController` exposure caps, optional daily drawdown on **balance** (live-specific; backtest needs a **simulated cash / equity** model).

Backtesting must feed **step (2)** with prices or books **as of simulated time**, not “now”.

### 2.3 Existing observability

- **`trade_ledger`** / `trade_events` / `trades.jsonl` — **append-only post-hoc** records; useful to **validate** a backtest against what actually happened in paper/live, not to drive simulation.
- **`scripts/parse_logs.py`** — reporting patterns could inspire **backtest output** (HTML/CSV).

---

## 3. External data — research summary

### 3.1 Polymarket CLOB (official)

| Capability | Use for backtest | Limitation |
| --- | --- | --- |
| **`GET /prices-history`** (`market` = token id, optional `startTs` / `endTs`, `interval`, `fidelity`) | Time series of **price points** `{t, p}` per outcome token | This is **not** full L2; typically used as **mid or last** proxy. Parameter name `market` is the **token id** (same id used for NO side in our strategy). See [CLOB timeseries docs](https://docs.polymarket.com/developers/CLOB/timeseries). |
| **`GET /book`** (current) | Live/paper only | No official **historical order book snapshot API** documented for arbitrary past timestamps. |

**Implication:** A **first-party–only** MVP backtest will be **midpoint- or trade-price–based**, with an explicit **spread model** (e.g. synthetic ask = min(1 - yes_mid, model) or fixed half-spread in ticks) unless we buy or ingest third-party L2.

### 3.2 Third-party historical L2 (example)

- Vendors such as **PolymarketData** advertise **minute-level historical L2** and slug-aligned endpoints (e.g. books + prices), suitable for **execution-aware** replay (walk the ask ladder for size). This is **paid**, **separate contract**, and would be an optional **Tier B** data source — not required to ship a useful Tier A.

### 3.3 Gamma / resolution

- **Gamma API** is already used for resolution checks (`_check_gamma_resolution` in `live_recovery.py`). For backtests that run **through** resolution, we need **final outcome** per market to mark PnL ($1 / $0 per share style). Resolved markets’ outcomes are available from Gamma-style endpoints; **exact historical “as-of” metadata** for every past day is harder — many backtests instead fix an **event set** (list of slugs + token ids) and only need end-of-life outcome.

### 3.4 Discovery bias (important)

- **`fetch_candidate_markets`** today reflects **current** Gamma open markets and filters. For a past window, the **set of markets that existed and were “discoverable”** is not trivially reconstructable without **snapshots** of Gamma (or a frozen list of slugs/token ids for the experiment).
- **Practical approach:** Phase 1 backtests should use a **user-supplied universe file** (slug, `no_token_id`, `end_ts`, optional category) captured once, or a **curated list** of resolved markets for research — not “whatever Gamma returns today.”

---

## 4. Fidelity tiers (recommended product framing)

| Tier | Data | Fill model | Credibility | Effort |
| --- | --- | --- | --- | --- |
| **A — Mid / history proxy** | `prices-history` for NO token (and/or derive NO from YES if only one side stored) | Synthetic book: e.g. ask = clamp(mid + spread_model), size = large | Good for **ranking configs** and rough PnL | Low |
| **B — L2 snapshots** | External minute L2 or self-collected snapshots | Walk asks to fill `target_notional`; partial fill optional | Better **slippage / size** realism | Medium + data cost |
| **C — Event-driven matching** | Same as B + queue model | Limit orders in book, matching engine | Research-grade; heavy | High |

**Recommendation:** Ship **Tier A** behind a flag `--backtest-fidelity mid`, design **`Exchange` interface** so **Tier B** can plug in later without rewriting the strategy loop.

---

## 5. Architecture proposal

### 5.1 Core idea: simulated clock + historical exchange

- Introduce a **`HistoricalClock`** (or inject `now_fn` / `sim_time`) used anywhere the strategy compares **event time** vs **market end** and schedules polls.
- Implement **`HistoricalExchange`** (or `ReplayExchange`) implementing the same methods the strategy needs:

  - `get_order_book(token_id)` → returns a snapshot **for `sim_time`** from preloaded series or L2 store.
  - `get_collateral_balance` / `get_conditional_balance` → return **simulated** wallet state updated by the backtest runner.
  - `place_market_order` / fills → update simulated balances; no HTTP.

- **Refactor surface (minimal):** Prefer **thin** changes to `NothingHappensRuntime` — e.g. optional `clock` and `exchange` constructed for replay — rather than duplicating the whole strategy file. Longer term, extract **pure** “would we enter at this book + cfg?” into a function to unit-test without asyncio.

### 5.2 Runner modes

| Mode | Description |
| --- | --- |
| **CLI** | `python -m bot.backtest run --config backtest.yaml --universe markets.csv --from ... --to ...` — fits automation and CI. |
| **Library** | `run_backtest(scenario)` returning a result object — for notebooks and tests. |
| **Dashboard (later)** | Upload universe + date range, job queue, results page — **Phase 3+**; not required for value. |

### 5.3 Data prep pipeline

1. **Universe builder** (one-off script): given slugs or Gamma query **at research time**, output `universe.jsonl` with `slug`, `no_token_id`, `condition_id`, `end_ts`, `question`.
2. **Price fetcher**: for each token, call `prices-history` with `[startTs, endTs]` aligned to backtest window; store **Parquet or SQLite** locally (rate limits → cache aggressively).
3. **Backtest engine**: step `sim_time` at configurable resolution (e.g. 1h or 15m bars first; match `fidelity` to avoid false precision).

### 5.4 Risk and PnL in backtest

- **Exposure caps** — wire existing `RiskController` with **simulated** `open_exposure_*` updates on each simulated fill (already conceptually aligned).
- **Daily drawdown on balance** — either **disable** in backtest v1 or feed **simulated USDC equity** each step (mark positions to mid or to resolution at end).
- **Resolution PnL** — at `end_ts` (or next bar after), apply **binary payoff** for NO position using Gamma outcome (or CSV ground truth for Tier A tests).

### 5.5 Outputs

- **Trades table** — same schema spirit as ledger (slug, time, side, price, notional, shares).
- **Equity curve** — CSV + optional HTML report (reuse styling ideas from `parse_logs.py`).
- **Summary metrics** — total return, max drawdown, # entries, time in market, hit rate (if resolutions known), comparison vs baseline config.

---

## 6. Phased delivery plan

| Phase | Scope | Exit criteria |
| --- | --- | --- |
| **0 — Spike (few days)** | Fetch `prices-history` for 3–5 NO tokens; document field mapping vs `get_order_book`; prototype **one** manual replay of “would enter?” at a single timestamp. | Written spike notes + sample notebook or script in `scripts/` |
| **1 — Tier A engine** | `HistoricalExchange` + stepped `sim_time` + universe file; **single-threaded** loop (can still use asyncio with frozen clock); no dashboard. | Reproducible CLI run; golden-file test on tiny fixture |
| **2 — Parity features** | ETA filters, `max_end_date_months` equivalent on universe, risk caps, multi-market interleaving same as live ordering assumptions. | Metrics within expected bounds vs simplified analytical case |
| **3 — UX & CI** | Documented workflow; optional GitHub Action on fixture-only backtest (no network). | Doc + CI job |
| **4 — Tier B (optional)** | Adapter for external L2 provider; spread calibration report. | Side-by-side Tier A vs B on same universe |

---

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| **Lookahead bias** (using knowledge from future discovery) | Freeze **universe at T0** per run; document that “dynamic Gamma replay” is out of scope for v1. |
| **Survival bias** (only resolved winners) | Offer explicit **“resolved markets sample”** mode and warn when extrapolating to live. |
| **API limits / gaps** | Cache downloads; fail runs with clear “missing bar” errors; optional interpolation flag (off by default). |
| **NO vs YES price symmetry** | Validate `p` in history corresponds to the **token id** passed (NO token); add tests with known markets. |
| **Overfitting** | Encourage **walk-forward** (train params on window A, validate on B) in docs; not enforced in code v1. |

---

## 8. Open questions (to decide before implementation)

1. **Default universe:** curated file vs “export from one live run’s `_markets_by_slug` snapshot”?
2. **Bar size:** align with `price_poll_interval_sec` or independent (coarser bars = faster, optimistic fills)?
3. **Fees:** Polymarket fee schedule by category — include in Tier A as configurable bps?
4. **Multi-outcome / neg-risk:** explicitly **out of scope** until standalone-only backtest is stable?

---

## 9. References (external)

- Polymarket CLOB **price history**: [developers/CLOB/timeseries](https://docs.polymarket.com/developers/CLOB/timeseries)  
- Polymarket **order book** (live): [trading/orderbook](https://docs.polymarket.com/trading/orderbook)  
- Example third-party **historical L2**: [PolymarketData order book data](https://www.polymarketdata.co/polymarket-order-book-data) (illustrative; not an endorsement)

---

## 10. Summary

A **viable backtest** for this repo should:

1. **Decouple** the strategy from wall clock and live HTTP via a **historical exchange** + **simulated time**.  
2. Start with **Tier A** using official **`prices-history`**, synthetic spread, and a **frozen universe** to avoid discovery lookahead.  
3. Add **Tier B** only if execution realism justifies **external L2** cost and integration.  
4. Ship as **CLI + cached data** first; dashboard integration later.

This matches the existing architecture (`NothingHappensConfig`, exchange interface, risk module) while being honest about **Polymarket’s public historical surface** (strong on prices, weak on historical L2).
