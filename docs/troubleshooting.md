# Troubleshooting

## Dashboard: 401 on `/ws` or main page {: #dashboard-401 }

- **Not logged in** — open `/login` first.  
- **Stale cookie** — clear site cookies or use a private window.  
- **HTTP vs HTTPS** — behind a proxy, confirm **`X-Forwarded-Proto`** is set so the app treats the session as secure.

## Settings saved but behavior unchanged {: #settings-no-effect }

Restart the bot process. Runtime settings are applied at **startup**; the in-memory exchange client does not hot-reload.

## Live mode still paper {: #live-still-paper }

Check all three gates: `BOT_MODE=live`, `LIVE_TRADING_ENABLED=true`, `DRY_RUN=false` in **effective** configuration (remember DB overrides `.env`). See [Trading & safety](trading-and-safety.md#three-live-gates).

## Orders rejected / auth errors {: #orders-auth }

- **`signature_type`** vs actual Polymarket account type.  
- Missing **`FUNDER_ADDRESS`** for proxy modes.  
- Invalid or funding-depleted wallet; API credentials derived from `PRIVATE_KEY` must match the funded account.

## SQLite locked {: #sqlite-locked }

WAL mode and busy timeouts are enabled; heavy concurrent access from external tools can still block. Avoid long read transactions against the bot DB file while trading.

## Help pages 404 {: #help-404 }

In-app help is built from **`docs/user/`**. If that folder is missing on the server (partial deploy), `/help` returns **404**. Ensure the full repository is checked out.

## Recent trades empty or split across two files {: #trades-ledger-mismatch }

The dashboard tails **`TRADE_LEDGER_PATH`** from the environment **after** DB `runtime_settings` are applied at startup. If `.env` pointed at one path and **Admin → Settings** stored a different `TRADE_LEDGER_PATH`, older builds could append new lines to the wrong file while the UI read another. Keep **one** path (prefer an **absolute** path) in both `.env` and runtime settings, or clear the DB row to fall back to `.env`.

## Related docs

- [Configuration overview](configuration-overview.md)  
- [Deployment](deployment.md)
