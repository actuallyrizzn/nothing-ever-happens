# Dashboard UI

The main dashboard is a single-page app backed by a **WebSocket** (`/ws`) that streams portfolio snapshots, trade ledger events, and control metadata.

## WebSocket connection {: #websocket-connection }

The pill in the top-right shows **socket: connected** (green) or **socket: disconnected** (red).

- When **disconnected**, the UI stops updating until the browser reconnects (e.g. after a network blip or bot restart).
- The WebSocket requires a valid **session cookie** when dashboard authentication is enabled; unauthenticated clients get **401** on `/ws`.

## Portfolio summary {: #portfolio-summary }

The eight tiles summarize what the strategy loop last published:

| Tile | Meaning |
| --- | --- |
| **Monitored** | Standalone yes/no markets passing discovery filters (Gamma API). |
| **Eligible** | Monitored markets where you have **no** open position on the tracked side. |
| **In Range** | Eligible markets whose last observed **NO ask** is at or below **max entry price** (strategy cap). |
| **Open Positions** | Count from the in-memory portfolio sync (positions API / exchange layer depending on mode). |
| **Cash** | Collateral balance used for sizing (paper wallet or live USDC balance). |
| **Portfolio** | Cash + marked-to-mid position value. |
| **Session PnL** | Change vs the first balance observation this process saw (informational). |
| **Last Error** | Last error string from the strategy loop; **none** if clean. |

Sub-lines show **last position sync**, **last price cycle**, **last market refresh**, etc., as human-readable ages.

## Position cap {: #position-cap }

Shows the **target open positions** control state (how many new entries the strategy is allowed to open this run), plus **pending** entries, **remaining** capacity, and how many were **opened this session**.

When controls are driven only from env/DB defaults, the note may read **env configured**. See [Runtime settings](runtime-settings.md#paths--logging) if you tune related flags from the admin form.

## Open positions table {: #open-positions-table }

Sortable columns:

- **Market** — title + slug (links to Polymarket when available).  
- **Side** — outcome held (e.g. **No**).  
- **Size / Avg paid / Current** — share economics.  
- **Market value / PnL** — mark-to-mid.  
- **Pot. Win** — upside if the position pays $1 per share.  
- **ETA** — time until market **end** (not execution ETA).

## Recent trades & ledger {: #recent-trades--ledger }

Tail of the **trade ledger**: attempts, fills, recovery events, etc. The same stream is written to SQLite (`trade_events`) and optionally to a JSONL file (`TRADE_LEDGER_PATH`). See [Configuration overview](configuration-overview.md).

## Related docs

- [Trading & safety](trading-and-safety.md) — why cash/positions differ in paper vs live.  
- [Strategy parameters](strategy-parameters.md) — what drives **In range** and sizing.  
- [Admin & authentication](admin-and-auth.md) — login and session behavior.
