# Nothing Ever Happens Polymarket Bot

Focused async Python bot for Polymarket that buys No on standalone non-sports yes/no markets.

*FOR ENTERTAINMENT ONLY. PROVIDED AS IS, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. USE AT YOUR OWN RISK. THE AUTHORS ARE NOT LIABLE FOR ANY CLAIMS, LOSSES, OR DAMAGES.*

![Dashboard screenshot](docs/dashboard.jpg)

- `bot/`: runtime, exchange clients, dashboard, recovery, and the `nothing_happens` strategy
- `scripts/`: operational helpers for deployed instances and local inspection
- `tests/`: focused unit and regression coverage

## Runtime

The bot scans standalone markets, looks for NO entries below a configured price cap, tracks open positions, exposes a dashboard, and persists live recovery state when order transmission is enabled.

The runtime is `nothing_happens`.

## Safety Model

Real order transmission requires all three environment variables:

- `BOT_MODE=live`
- `LIVE_TRADING_ENABLED=true`
- `DRY_RUN=false`

If any of those are missing, the bot uses `PaperExchangeClient`.

Additional live-mode requirements:

- `PRIVATE_KEY`
- `FUNDER_ADDRESS` for signature types `1` and `2`
- **SQLite database** for durable ledger and live recovery (see **Database** below)
- `POLYGON_RPC_URL` for proxy-wallet approvals and redemption

## Database (SQLite only)

All structured bot state uses **SQLite** via SQLAlchemy: `trade_events`, `ambiguous_orders`, `pending_settlements`, and related tables.

- If **`DATABASE_URL`** is unset, the default file is **`nothing_happens.sqlite`** in the process working directory (absolute path is embedded in the URL).
- Set **`DATABASE_URL=sqlite:////absolute/path/to/file.sqlite`** to choose the file explicitly.
- Or set **`NOTHING_HAPPENS_SQLITE_PATH`** to a path/filename (resolved relative to cwd at startup) when you do not want to spell a full URL.

**PostgreSQL is not supported** (no `DATABASE_URL` pointing at Postgres).

The bot enables **WAL mode** and a busy timeout on SQLite connections to reduce lock contention for this single-process, single-tenant design.

Dashboard admin users (optional) use a **separate** SQLite file: **`DASHBOARD_AUTH_DB_PATH`** (default `dashboard_auth.sqlite`).

## Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
cp .env.example .env
```

`config.json` is intentionally local and ignored by git.

## Configuration

The runtime reads, in order:

1. **`config.json`** — defaults for connection + `strategies.nothing_happens` (and optional `PM_*` / `BOT_*` env vars if set).
2. **`runtime_settings` table** (in the **same SQLite file** as `trade_events`) — written from **Admin → Settings** on the dashboard. On first boot, if this table is empty, it is **seeded** from `config.example.json` / your `config.json` (non-secret keys only). At startup, each stored row is applied into `os.environ`, so it overrides `.env` / `config.json` for that process.

**Bootstrap-only `.env`:** you still need a way to find SQLite (`DATABASE_URL` or `NOTHING_HAPPENS_SQLITE_PATH`) and, for a public dashboard, `DASHBOARD_AUTH_SECRET` (+ bind/port). Everything else can live in the database once configured there.

**Restart:** changing settings in the UI updates SQLite immediately, but the **running** strategy and CLOB client are built at startup — **restart the bot** to apply trading, connection, and log-level changes.

See [config.example.json](config.example.json) and [.env.example](.env.example).

You can point the runtime at a different config file with `CONFIG_PATH=/path/to/config.json`.

## Running Locally

```bash
python -m bot.main
```

The dashboard binds `$PORT` or `DASHBOARD_PORT` when one is set.

### Dashboard authentication (VPS / public bind)

When **`DASHBOARD_AUTH_SECRET`** is set (at least 32 characters), the dashboard uses **SQLite admin users** (via **`DASHBOARD_AUTH_DB_PATH`**, default `dashboard_auth.sqlite`), **bcrypt** passwords, **CSRF** on POST forms, and a **signed session cookie** (7-day TTL). Without that env var, behavior is unchanged (no login).

- **`DASHBOARD_BOOTSTRAP_USERNAME`** / **`DASHBOARD_BOOTSTRAP_PASSWORD`** — optional; if the user table is empty at startup, one admin is created (useful for first deploy).
- **`python scripts/dashboard_create_user.py --username … --password …`** — create admins anytime (requires `DASHBOARD_AUTH_SECRET` in the environment).

Routes: **`/login`**, **`/logout`** (POST), **`/admin/users`**, **`/admin/change-password`**. The trading UI injects a small **Admin / Password / Logout** bar when auth is on.

Use **HTTPS** in production (`Secure` cookies follow `X-Forwarded-Proto: https` behind a reverse proxy).

## Deployment (single host / VPS)

Run `python -m bot.main` under your process manager (systemd, Docker, etc.). Set the same env vars as in `.env.example` (keys, `POLYGON_RPC_URL`, SQLite paths, optional `PORT` for the dashboard).

Optional shell helpers (`alive.sh`, `logs.sh`, …) target **Heroku-style** CLIs if you still use them; the app itself does not require Heroku.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Documentation

- **In the dashboard:** **`/help`** serves plain-language guides from [`docs/user/`](docs/user/) only.  
- **Developers & hosting:** technical Markdown lives in [`docs/`](docs/README.md) (configuration, deployment, env keys, etc.) and is **not** shown inside the dashboard UI.

## Included Scripts

| Script | Purpose |
| --- | --- |
| `scripts/db_stats.py` | Inspect `trade_events` in the SQLite DB (last 2h stats) |
| `scripts/export_db.py` | Export tables from the SQLite DB to CSV |
| `scripts/wallet_history.py` | Pull positions, trades, and balances for the configured wallet |
| `scripts/parse_logs.py` | Convert JSON logs into readable terminal or HTML; `--db` reads `trade_events` from SQLite |

## License

This repository uses two copyright licenses:

- **Software (code)** — Python modules under `bot/`, `scripts/`, and `tests/`, and any other material clearly offered as program source: **GNU Affero General Public License v3.0 only** (`AGPL-3.0-only`). Full text: [`LICENSE`](LICENSE).
- **Everything else** — documentation (including this `README.md`, `docs/`, and user guides), images, static assets, JSON/YAML examples such as `config.example.json` and `.env.example`, and similar non-program creative material: **Creative Commons Attribution-ShareAlike 4.0 International** (`CC-BY-SA-4.0`). Full legal text: [`LICENSE-CC-BY-SA-4.0.txt`](LICENSE-CC-BY-SA-4.0.txt).

Dependencies installed from PyPI (see `requirements.txt`) remain under their upstream licenses. The previous repository-wide **CC0 1.0** dedication no longer applies.

## Repository Hygiene

Local config, ledgers, exports, reports, and deployment artifacts are ignored by default.
