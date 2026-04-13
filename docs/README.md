# Documentation index (repository)

## End-user help (also in the dashboard)

The dashboard serves **`/help`** from Markdown in **`docs/user/`** only—plain-language guides for people using the UI. Edit those files if you want to change in-app help.

| File | In-app URL |
| --- | --- |
| [user/README.md](user/README.md) | `/help` |
| [user/main-dashboard.md](user/main-dashboard.md) | `/help/main-dashboard` |
| [user/your-account.md](user/your-account.md) | `/help/your-account` |
| [user/settings.md](user/settings.md) | `/help/settings` |
| [user/trading-modes.md](user/trading-modes.md) | `/help/trading-modes` |

---

## Developer & server reference (repository only)

These are **not** linked from the dashboard UI. Use them when editing code, hosting, or debugging.

| Topic | File |
| --- | --- |
| Config merge order, env, `runtime_settings` | [configuration-overview.md](configuration-overview.md) |
| Technical dashboard / WebSocket detail | [dashboard-ui.md](dashboard-ui.md) |
| Admin form field → env keys | [runtime-settings.md](runtime-settings.md) |
| Live gates, keys, signature types | [trading-and-safety.md](trading-and-safety.md) |
| `PM_NH_*` reference | [strategy-parameters.md](strategy-parameters.md) |
| `PM_RISK_*` reference | [risk-controls.md](risk-controls.md) |
| Backtesting (proposed plan) | [backtesting-proposal.md](backtesting-proposal.md) |
| Auth implementation detail | [admin-and-auth.md](admin-and-auth.md) |
| Deploy, nginx, paths | [deployment.md](deployment.md) |
| Incident-style checks | [troubleshooting.md](troubleshooting.md) |

## Repository layout (reference)

- `bot/` — runtime, strategy, exchange clients, dashboard, `runtime_settings` loader  
- `docs/user/` — **in-app** help source  
- `docs/*.md` — **technical** docs (this index + references above)  
- `config.example.json` — non-secret defaults for `config.json`  
- `.env.example` — bootstrap-only environment variables  
- `scripts/` — CLI helpers  

---

*For entertainment only. No warranty. Trading involves risk.*
