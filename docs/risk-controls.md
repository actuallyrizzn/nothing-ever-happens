# Risk controls (`PM_RISK_*`)

`RiskController` (`bot/risk_controls.py`) enforces exposure caps and an optional **balance-based daily drawdown** breaker on top of strategy logic.

## Exposure caps {: #exposure }

- **`PM_RISK_MAX_TOTAL_OPEN_EXPOSURE_USD`** — maximum **open** notional summed across all markets.  
- **`PM_RISK_MAX_MARKET_OPEN_EXPOSURE_USD`** — per-market (slug) open notional cap.

When exceeded, new risk-increasing actions are blocked until exposure drops (e.g. after sells or settlement).

## Drawdown breaker {: #drawdown }

When **`PM_RISK_MAX_DAILY_DRAWDOWN_USD` &gt; 0**, the controller compares **live USDC collateral balance** to a **daily high-water mark**:

- **`PM_RISK_DRAWDOWN_ARM_AFTER_SEC`** — wait time before arming drawdown logic after startup.  
- **`PM_RISK_DRAWDOWN_MIN_FRESH_OBS`** — minimum fresh balance observations required before arming.  
- **`PM_RISK_KILL_COOLDOWN_SEC`** — after a kill triggers, cooldown before re-enabling entries.

If **`PM_RISK_MAX_DAILY_DRAWDOWN_USD`** is **0**, drawdown based on balance is **disabled** (legacy PnL-only fields may still exist in the struct but are not the primary breaker in live balance mode — see code for the exact integration path).

## Related docs

- [Runtime settings — risk](runtime-settings.md#risk)  
- [Trading & safety](trading-and-safety.md)
