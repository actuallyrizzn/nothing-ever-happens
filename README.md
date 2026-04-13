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
- `DATABASE_URL`
- `POLYGON_RPC_URL` for proxy-wallet approvals and redemption

## Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
cp .env.example .env
```

`config.json` is intentionally local and ignored by git.

## Configuration

The runtime reads:

- `config.json` for non-secret runtime settings
- `.env` for secrets and runtime flags

The runtime config lives under `strategies.nothing_happens`. See [config.example.json](config.example.json) and [.env.example](.env.example).

You can point the runtime at a different config file with `CONFIG_PATH=/path/to/config.json`.

## Running Locally

```bash
python -m bot.main
```

The dashboard binds `$PORT` or `DASHBOARD_PORT` when one is set.

### Dashboard authentication (VPS / public bind)

When **`DASHBOARD_AUTH_SECRET`** is set (at least 32 characters), the dashboard uses the same ideas as other Decision Science Corp admin panels: **SQLite admin users** (file path via **`DASHBOARD_AUTH_DB_PATH`**, default `dashboard_auth.sqlite` — separate from **`DATABASE_URL`** / Postgres for trading data), **bcrypt** passwords, **CSRF** on POST forms, and a **signed session cookie** (7-day TTL). Without that env var, behavior is unchanged (no login).

- **`DASHBOARD_AUTH_DB_PATH`** — SQLite file for `admin_users` (use a persistent path on a VPS, e.g. under a mounted volume).
- **`DASHBOARD_BOOTSTRAP_USERNAME`** / **`DASHBOARD_BOOTSTRAP_PASSWORD`** — optional; if the user table is empty at startup, one admin is created (useful for first deploy).
- **`python scripts/dashboard_create_user.py --username … --password …`** — create admins anytime (requires `DASHBOARD_AUTH_SECRET` in the environment).

Routes: **`/login`**, **`/logout`** (POST), **`/admin/users`**, **`/admin/change-password`**. The trading UI injects a small **Admin / Password / Logout** bar when auth is on.

Use **HTTPS** in production (`Secure` cookies follow `X-Forwarded-Proto: https` behind a reverse proxy).

## Heroku Workflow

The shell helpers use either an explicit app name argument or `HEROKU_APP_NAME`.

```bash
export HEROKU_APP_NAME=<your-app>
./alive.sh
./logs.sh
./live_enabled.sh
./live_disabled.sh
./kill.sh
```

Generic deployment flow:

```bash
heroku config:set BOT_MODE=live DRY_RUN=false LIVE_TRADING_ENABLED=true -a "$HEROKU_APP_NAME"
heroku config:set PRIVATE_KEY=<key> FUNDER_ADDRESS=<addr> POLYGON_RPC_URL=<url> DATABASE_URL=<url> -a "$HEROKU_APP_NAME"
git push heroku <branch>:main
heroku ps:scale web=1 worker=0 -a "$HEROKU_APP_NAME"
```

Only run the `web` dyno. The `worker` entry exists only to fail fast if it is started accidentally.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Included Scripts

| Script | Purpose |
| --- | --- |
| `scripts/db_stats.py` | Inspect live database table counts and recent activity |
| `scripts/export_db.py` | Export live tables from `DATABASE_URL` or a Heroku app |
| `scripts/wallet_history.py` | Pull positions, trades, and balances for the configured wallet |
| `scripts/parse_logs.py` | Convert Heroku JSON logs into readable terminal or HTML output |

## Repository Hygiene

Local config, ledgers, exports, reports, and deployment artifacts are ignored by default.
