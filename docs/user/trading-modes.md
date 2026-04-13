# Trading modes

## Practice vs real money {: #practice-vs-live }

The bot can run in two broad styles:

- **Practice (paper)** — nothing is sent to the real exchange. Balances and fills are simulated so you can watch behavior without risking funds.  
- **Live** — the bot can place **real** orders with **real** money. Mistakes can cost money.

**Live trading is serious.** Only turn it on when you understand the risk and you intend to trade for real.

## What “live” really means {: #what-live-means }

Turning on live trading is not a single switch. **All** of the following must be set to allow real orders (whoever runs the bot configures this in **Settings** or on the server):

1. Mode set to **live** (not practice).  
2. **Live trading** explicitly enabled.  
3. **Dry run** turned **off** (dry run means “pretend,” even if other flags look live).

If any one of those is wrong, the bot stays in a safe, non‑sending mode.

## Wallet and keys {: #wallet-keys }

For live trading, the bot needs the right **wallet keys** and **account type** for Polymarket. If those do not match how your account was set up, orders will fail or not send. When in doubt, get help from whoever maintains the bot or your wallet setup—do not paste private keys into chat or email.

## After you change settings {: #after-changes }

Saving **Settings** updates what is stored for the next time the bot **starts**. The copy that is already running does not fully reload everything instantly—**restart the bot** (whoever operates the server does this) so connection and trading behavior match what you saved.
