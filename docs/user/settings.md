# Settings

**Settings** is where trading behavior, wallet connection, and timing are changed. Nothing here takes effect for the **running** bot until it is **restarted** (whoever runs the server handles that).

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

These control **how often** the bot looks at markets and prices, **how big** each trade is, **how high** a price you are willing to pay for a “No” share, **retries**, and **limits** on how many new positions to open. Labels on the form match what you see here—tighter caps and lower prices mean fewer, smaller, pickier trades.

## Risk {: #risk }

Caps on **how much** can be open at once, per market and in total, and optional **drawdown** rules that can pause trading if the account balance drops too far in a day. Zero drawdown limit usually means that particular safety is off—confirm with your operator if you are unsure.

## Related {: #related-settings }

- **[Trading modes](trading-modes.md)** — practice vs live.  
- **[Main dashboard](main-dashboard.md)** — what the numbers mean after you change things.
