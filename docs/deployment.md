# Deployment

Single-process design: **`python -m bot.main`** runs the strategy asyncio loop, optional feeds, and the aiohttp dashboard on one port.

## Process manager {: #process-manager }

Use **systemd**, **supervisor**, **screen**/**tmux**, or Docker with a restart policy. Ensure:

- Working directory contains `config.json` or `CONFIG_PATH` points to it.  
- `.env` or the environment provides **SQLite path** and **dashboard auth** secrets.  
- SQLite files live on **persistent** disk.

## Reverse proxy {: #reverse-proxy }

Typical VPS layout:

- Dashboard binds **`127.0.0.1:PORT`** (e.g. `8891`).  
- **nginx** (or similar) terminates TLS and proxies to the loopback port.  
- Set **`X-Forwarded-Proto: https`** so **Secure** cookies work.

## Database files {: #database-files }

- **Bot DB** — `trade_events`, `runtime_settings`, recovery tables, etc.  
- **Admin DB** — separate SQLite file (`DASHBOARD_AUTH_DB_PATH`) for bcrypt users.

Back up both for disaster recovery. **Do not** commit them to git.

## Applying updates {: #applying-updates }

1. `git pull`  
2. `pip install -r requirements.txt` (if dependencies changed)  
3. Restart the process (new columns/tables are created via SQLAlchemy `create_all` on startup).

After pulling versions with **`runtime_settings`**, the first restart may **seed** defaults if the table was empty.

## Related docs

- [Configuration overview](configuration-overview.md)  
- [Troubleshooting](troubleshooting.md)
