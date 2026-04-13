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

## Restart from the dashboard (cron + flag) {: #restart-from-dashboard }

Runtime settings apply at **process startup**. If operators only have the **web UI**, they can still request a restart **without SSH** if you enable a small flag file + cron loop (the running bot does **not** restart itself—that would tear down the HTTP handler mid-request).

1. In **`.env`**, set a path the bot may create, e.g.  
   `NEH_RESTART_FLAG_PATH=/absolute/path/to/data/.neh_restart_requested`
2. **`chmod +x scripts/neh_cron_restart.sh`** and install a **cron** job (as the same user that runs the bot), e.g. every minute:  
   `* * * * * NEH_HOME=/path/to/repo NEH_RESTART_FLAG_PATH=/path/to/data/.neh_restart_requested /path/to/repo/scripts/neh_cron_restart.sh >>/path/to/repo/logs/cron_restart.log 2>&1`
3. After deploy, **Admin → Settings** shows a **Request bot restart after this save** checkbox when `NEH_RESTART_FLAG_PATH` is set.

The script defaults to **GNU screen** (`NEH_SCREEN_SESSION`, default `nothing-ever-happens`). If you use **systemd**, keep the flag + env the same, but edit the script’s restart block to call `systemctl restart your-unit.service` instead of `screen`.

**Alternatives:** long term, a **systemd** unit with `systemctl restart` invoked from a **setuid helper** or **polkit** is more integrated than cron; **hot-reloading** strategy/exchange from SQLite without restart is possible but touches a large part of the codebase and is easier to get wrong than “restart process.”

## Related docs

- [Configuration overview](configuration-overview.md)  
- [Troubleshooting](troubleshooting.md)
