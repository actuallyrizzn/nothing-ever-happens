# Strategy parameters (`PM_NH_*`)

These settings control the **nothing_happens** loop: discovery, filtering, pricing, order sizing, retries, and optional redeemer timing. They correspond to `strategies.nothing_happens` in `config.json` and can be overridden from **Admin → Settings** or the environment.

Validation rules match `bot/config.py` (`_validate_nothing_happens_config`).

## Timing & cadence {: #timing }

- **Market refresh** — pulls standalone markets from Gamma; larger values reduce API load. Minimum **60** seconds.  
- **Price poll** — how often eligible markets are re-priced. Minimum **15** seconds.  
- **Position sync** — refreshes cash and open positions from the exchange / data API. Minimum **15** seconds.  
- **Order dispatch** — how often the bot attempts new entries when capacity allows. Minimum **15** seconds.  
- **Redeemer interval** — how often the on-chain redeemer runs **when constructed** (live + proxy + RPC). Minimum **60** seconds.

## Sizing & entry rules {: #sizing }

- **Cash % per trade** — fraction of current cash allocated per new BUY, upper bounded by **1.0**.  
- **Min trade amount** — minimum USD notional; skips markets where computed size is below this.  
- **Fixed trade amount** — when **&gt; 0**, interacts with percentage sizing (see runtime code for the effective path).  
- **Max entry price** — only considers **NO** asks at or below this price (probability cap).  
- **Allowed slippage** — tolerance when comparing working prices to limits.

## Concurrency & retries {: #retries }

- **Request concurrency** — parallel fetches for books / mids across markets.  
- **Buy retry count / base delay / max backoff** — backoff ladder for transient CLOB or network failures.

## Position limits {: #position-limits }

- **Max new positions** — `-1` means unlimited new opens; non-negative values cap how many *new* positions can be opened in a run (see control state on the dashboard).  
- **Shutdown on max positions** — when true, hitting the cap stops further opens.

## Related docs

- [Dashboard UI — position cap](dashboard-ui.md#position-cap)  
- [Runtime settings — strategy section](runtime-settings.md#strategy)  
- [Trading & safety](trading-and-safety.md)
