# Configuration overview

Configuration is layered. Later layers override earlier ones for keys they define.

## Order of precedence {: #precedence }

1. **`config.json`** (or `CONFIG_PATH`) — baseline **connection** (`host`, `chain_id`, `signature_type`) and **`strategies.nothing_happens`** numeric defaults.  
2. **Environment variables** — loaded via `python-dotenv` from `.env` at process start (optional). Historically used for `PM_NH_*`, `PM_RISK_*`, `BOT_MODE`, secrets, etc.  
3. **`runtime_settings` SQLite table** — rows are applied into `os.environ` **after** `init_db` and **before** `load_nothing_happens_config()`. Any key stored here **wins** over `.env` and file defaults for that process.  
4. **Connection overlay** — `PM_CONNECTION_HOST`, `PM_CONNECTION_CHAIN_ID`, and `PM_CONNECTION_SIGNATURE_TYPE` from the environment (including DB-applied values) override the `connection` object from `config.json`.

## Bootstrap-only environment {: #bootstrap-env }

You still need a **database location** before the bot can read `runtime_settings`:

- `DATABASE_URL=sqlite:////absolute/path.db` **or**  
- `NOTHING_HAPPENS_SQLITE_PATH=relative/or/absolute.sqlite`

For a **public** dashboard, keep in `.env`:

- `DASHBOARD_AUTH_SECRET` (≥ 32 characters)  
- `DASHBOARD_HOST` / `DASHBOARD_PORT` (or `PORT`)  
- `DASHBOARD_AUTH_DB_PATH` if you do not want the default admin SQLite file  

Everything else can migrate to **Admin → Settings** once seeded.

## First startup & seeding {: #seeding }

If `runtime_settings` is **empty**, the bot **seeds** non-secret defaults from `config.example.json` and your existing `config.json`, then applies them. Secrets (`PRIVATE_KEY`, `FUNDER_ADDRESS`, `POLYGON_RPC_URL`) are **not** auto-seeded.

## Restart requirement {: #restart }

Saving the admin form updates SQLite **immediately**, but the **exchange client**, **strategy tasks**, and **thread pools** are created at **process startup**. **Restart the bot** after changing connection, trading mode, strategy intervals, or risk limits.

## Related docs

- [Runtime settings reference](runtime-settings.md)  
- [Trading & safety](trading-and-safety.md)  
- [Deployment](deployment.md)
