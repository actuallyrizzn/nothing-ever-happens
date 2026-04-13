# Runtime settings (admin form)

Values on **Admin → Settings** are stored in the **`runtime_settings`** table in the **same SQLite file** as `trade_events`. At **process startup**, each row is copied into `os.environ`, overriding `.env` and `config.json` defaults for matching keys.

**After saving**, restart the bot so the running exchange client and strategy loops pick up changes.

## Trading mode {: #trading-mode }

| Field | Env key | Description |
| --- | --- | --- |
| Bot mode | `BOT_MODE` | `paper` or `live`. `live` alone does not send orders; see [Trading & safety](trading-and-safety.md#three-live-gates). |
| Dry run | `DRY_RUN` | `true` blocks live transmission even if other flags suggest live. |
| Live trading enabled | `LIVE_TRADING_ENABLED` | Must be `true` with `BOT_MODE=live` and `DRY_RUN=false` for real orders. |

## Secrets {: #secrets }

| Field | Env key | Description |
| --- | --- | --- |
| Private key | `PRIVATE_KEY` | CLOB signing key. Leave blank on save to **keep** the previous value. |
| Funder / proxy address | `FUNDER_ADDRESS` | Required for `signature_type` 1 or 2. |
| Polygon RPC URL | `POLYGON_RPC_URL` | JSON-RPC endpoint for Polygon. Needed for on-chain flows (e.g. redeemer with proxy). |

Protect the SQLite file: it holds secrets in plaintext. Restrict filesystem permissions and backups.

## Polymarket connection {: #polymarket-connection }

| Field | Env key | Description |
| --- | --- | --- |
| CLOB host | `PM_CONNECTION_HOST` | Default `https://clob.polymarket.com`. |
| Chain ID | `PM_CONNECTION_CHAIN_ID` | `137` for Polygon mainnet. |
| Signature type | `PM_CONNECTION_SIGNATURE_TYPE` | `0`, `1`, or `2` — must match your Polymarket account model. |

These override `connection` in `config.json` when set in the DB.

## Paths & logging {: #paths--logging }

| Field | Env key | Description |
| --- | --- | --- |
| Trade ledger (JSONL) | `TRADE_LEDGER_PATH` | Append-only JSON lines mirrored from the dashboard tail. |
| Log level | `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| Background executor workers | `PM_BACKGROUND_EXECUTOR_WORKERS` | Thread pool size for blocking CLOB calls (minimum practical value enforced at runtime). |
| Bot variant tag | `BOT_VARIANT` | Optional string attached to ledger rows for multi-instance labeling. |

Clearing a **non-secret** field and saving **removes** the row so `config.json` / `.env` apply again for that key.

## Strategy {: #strategy }

All keys are prefixed `PM_NH_` and map to `strategies.nothing_happens` in `config.json` when not overridden.

| Field | Env key | Typical role |
| --- | --- | --- |
| Market refresh (sec) | `PM_NH_MARKET_REFRESH_INTERVAL_SEC` | How often to pull candidate markets from Gamma. **Minimum 60** enforced. |
| Price poll (sec) | `PM_NH_PRICE_POLL_INTERVAL_SEC` | Order book / mid polling cadence. **Minimum 15**. |
| Position sync (sec) | `PM_NH_POSITION_SYNC_INTERVAL_SEC` | Refresh open positions and cash. **Minimum 15**. |
| Order dispatch (sec) | `PM_NH_ORDER_DISPATCH_INTERVAL_SEC` | How often the loop tries new entries. **Minimum 15**. |
| Cash % per trade | `PM_NH_CASH_PCT_PER_TRADE` | Fraction of cash to allocate per new entry (0–1]. |
| Min trade amount (USD) | `PM_NH_MIN_TRADE_AMOUNT` | Floor notional per trade. |
| Fixed trade amount (USD) | `PM_NH_FIXED_TRADE_AMOUNT_USD` | If &gt; 0, can cap/size differently (see code paths). |
| Max entry price | `PM_NH_MAX_ENTRY_PRICE` | Max **NO** price willing to pay (0–1]. |
| Allowed slippage | `PM_NH_ALLOWED_SLIPPAGE` | Slippage tolerance for executable prices. |
| Request concurrency | `PM_NH_REQUEST_CONCURRENCY` | Parallelism for HTTP/CLOB reads. |
| Buy retry count | `PM_NH_BUY_RETRY_COUNT` | Retries on transient buy failures. |
| Buy retry base delay (sec) | `PM_NH_BUY_RETRY_BASE_DELAY_SEC` | Backoff base. |
| Max backoff (sec) | `PM_NH_MAX_BACKOFF_SEC` | Cap for exponential backoff. |
| Max new positions | `PM_NH_MAX_NEW_POSITIONS` | `-1` = unlimited. |
| Shutdown on max positions | `PM_NH_SHUTDOWN_ON_MAX_NEW_POSITIONS` | Stop opening when cap hit. |
| Redeemer interval (sec) | `PM_NH_REDEEMER_INTERVAL_SEC` | On-chain redeemer loop when enabled. **Minimum 60**. |

See [Strategy parameters](strategy-parameters.md) for behavioral detail.

## Risk {: #risk }

| Field | Env key | Description |
| --- | --- | --- |
| Max total open exposure (USD) | `PM_RISK_MAX_TOTAL_OPEN_EXPOSURE_USD` | Cap across all markets. |
| Max per-market exposure (USD) | `PM_RISK_MAX_MARKET_OPEN_EXPOSURE_USD` | Per slug / market cap. |
| Max daily drawdown (USD) | `PM_RISK_MAX_DAILY_DRAWDOWN_USD` | **0** disables balance-based drawdown breaker. |
| Kill-switch cooldown (sec) | `PM_RISK_KILL_COOLDOWN_SEC` | Cooldown after risk kill trips. |
| Drawdown arm after (sec) | `PM_RISK_DRAWDOWN_ARM_AFTER_SEC` | Delay before drawdown logic arms. |
| Drawdown min fresh observations | `PM_RISK_DRAWDOWN_MIN_FRESH_OBS` | Minimum balance samples before acting. |

See [Risk controls](risk-controls.md).

## Related docs

- [Configuration overview](configuration-overview.md)  
- [Dashboard UI](dashboard-ui.md)
