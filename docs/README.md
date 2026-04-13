# Nothing Ever Happens — documentation

Operator and developer reference for the Polymarket **nothing_happens** bot, its **dashboard**, and **runtime configuration**.

## Quick links

| Topic | Description |
| --- | --- |
| [Dashboard UI](dashboard-ui.md) | Main screen: summary tiles, WebSocket, positions, trades, position cap |
| [Configuration overview](configuration-overview.md) | How `config.json`, `.env`, and SQLite `runtime_settings` combine |
| [Runtime settings (admin form)](runtime-settings.md) | Every field on **Admin → Settings** explained |
| [Trading & safety](trading-and-safety.md) | Paper vs live, `BOT_MODE` / `DRY_RUN` / `LIVE_TRADING_ENABLED`, keys |
| [Strategy parameters](strategy-parameters.md) | `PM_NH_*` knobs: intervals, sizing, slippage, retries |
| [Risk controls](risk-controls.md) | `PM_RISK_*` exposure caps and drawdown breaker |
| [Admin & authentication](admin-and-auth.md) | Login, CSRF, users, passwords, HTTPS cookies |
| [Deployment](deployment.md) | Process managers, reverse proxy, SQLite paths |
| [Troubleshooting](troubleshooting.md) | Common failures and checks |

## In-app help

While the bot is running, open **`/help`** on the dashboard port (e.g. `https://your-host/help`). The same pages are served from this `docs/` folder as HTML. Contextual **?** or **docs** links in the UI jump to the right section.

## Repository layout (reference)

- `bot/` — runtime, strategy, exchange clients, dashboard, `runtime_settings` loader  
- `docs/` — this documentation (Markdown)  
- `config.example.json` — non-secret defaults for `config.json`  
- `.env.example` — bootstrap-only environment variables  
- `scripts/` — CLI helpers (`dashboard_create_user.py`, `export_db.py`, …)

---

*For entertainment only. No warranty. Trading involves risk.*
