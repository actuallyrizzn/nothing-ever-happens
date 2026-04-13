# Settings

**Settings** is where trading behavior, wallet connection, and timing are changed. Nothing here takes effect for the **running** bot until it is **restarted** (whoever runs the server handles that).

If your operator enabled **restart from the web** on the server, you may see **Request bot restart after this save**. Checking it writes a small flag file; a **cron** job on the machine restarts the bot (usually within about a minute). If that checkbox does not appear, restarts are still done on the host the old-fashioned way.

When the bot is in **paper / dry-run** mode, the bottom of this page shows **Paper wallet** actions: rebuild simulated balances from your **live Polymarket account** (read-only), or reset to the default **$100** practice wallet. Simulated state is stored in the bot database; the separate **trade ledger** file and `trade_events` table remain the audit trail.

## Trading mode {: #trading-mode }

- **Bot mode** — **practice (paper)** vs **live**. Live does not send real orders by itself; see **[Trading modes](trading-modes.md#what-live-means)**.  
- **Dry run** — when on, the bot will not send real orders even if other flags look “live.”  
- **Live trading enabled** — must be on, together with live mode and dry run off, for real orders.

## Wallet and connections {: #secrets }

Fields here are **sensitive**. Do not share screenshots that show them.

- **Private key** — your trading wallet key. Leave the box **empty** when saving if you want to keep the current stored key unchanged.  
- **Funder / proxy address** — required for some Polymarket account types (when you log in with email or use a proxy wallet).  
- **Polygon RPC URL** — an address the bot uses to talk to the Polygon network for certain on-chain steps. Your operator sets a reliable endpoint.

## Polymarket connection {: #polymarket-connection }

- **CLOB host** — almost always the default Polymarket trading API; change only if directed.  
- **Chain ID** — the network ID (commonly Polygon).  
- **Signature type** — must match **how your Polymarket account signs** (direct wallet vs proxy). Wrong type causes failures.

## Logs and files {: #paths--logging }

- **Trade ledger file** — where a copy of recent activity is appended on disk (useful for backups or tools).  
- **Log level** — how chatty diagnostic logs are (**Debug** is noisy).  
- **Background workers** — how much parallel work the bot does internally; adjust only if you know you need to.  
- **Bot variant** — optional label so multiple bots can be told apart in history.

Clearing a **non-secret** field and saving usually means “go back to the default from the server’s main config file.” Empty **secret** fields mean “keep what is already stored.”

## Strategy {: #strategy }

These control **how often** the bot looks at markets and prices, **how big** each trade is, **how high** a price you are willing to pay for a “No” share, **retries**, **limits** on how many new positions to open, and **which markets count as candidates** by resolution timing.

- **Max end date (months)** — how far out the bot searches for markets (calendar-style horizon).  
- **Min / max resolution ETA** — optional filters in **seconds** until the market ends: skip markets that resolve too soon, too late, or both. **0** means “no limit” on that side.

**Units (read carefully):**

- **Intervals** (market refresh, price poll, position sync, order dispatch, redeemer) are **whole seconds**, not percentages.  
- **Cash % per trade** is a **decimal fraction**, not basis points and not a whole-number percent. **0.02 = 2%** of available cash. **2** or **200** would be wrong.  
- **Min / fixed trade amounts** are **US dollars** (e.g. `5` = five dollars).  
- **Max entry price** and **allowed slippage** use Polymarket’s **0–1 price scale** (same scale as the order book). **0.65** is a 65¢-style cap, **not** `65` and **not** basis points. Slippage **0.30** means up to **+0.30** on that scale on buys—not “30 bps.”  
- **Concurrency, retries, max positions** are **counts** (integers), not percents.

The form shows a short **hint under each field** with the same idea.

## Risk {: #risk }

**Exposure** and **drawdown** caps are in **US dollars** of notional / balance change—not percentages of your account unless you choose numbers that happen to match that. **0** on daily drawdown turns that breaker off. Cooldown and “arm after” values are **seconds**.

The form includes a line under each risk field stating the unit.

## Related {: #related-settings }

- **[Trading modes](trading-modes.md)** — practice vs live.  
- **[Main dashboard](main-dashboard.md)** — what the numbers mean after you change things.
