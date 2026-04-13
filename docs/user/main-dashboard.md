# Main dashboard

This screen shows what the bot is doing right now. Numbers refresh automatically while you stay on the page.

## Live updates {: #websocket-connection }

In the top corner you should see that the feed is **connected**. If it says **disconnected**, the page will not update until your browser reconnects (try refreshing). You may need to sign in again if your session expired.

## Summary tiles {: #portfolio-summary }

The eight tiles are a quick snapshot:

| Tile | What it means |
| --- | --- |
| **Monitored** | Markets the bot is watching. |
| **Eligible** | Watched markets where you do not already hold a position on the side the bot cares about. |
| **In Range** | Eligible markets where the last price check was at or below your **maximum entry** (a limit you can change in Settings). |
| **Open Positions** | How many positions you hold right now. |
| **Cash** | Spendable balance the bot uses for sizing (practice balance or real balance, depending on mode). |
| **Portfolio** | Cash plus the current value of open positions. |
| **Session PnL** | Change since this run of the bot first saw your balance (rough session snapshot, not tax advice). |
| **Last Error** | The latest problem the bot reported, or **none** if things look clean. |

Smaller lines under some tiles show **how long ago** the bot last refreshed markets, prices, or positions.

## Position cap {: #position-cap }

This strip shows how many **new** positions the bot is allowed to open in this run, how many are **pending**, how much **room** is left, and how many have **opened** already. If it says the target comes from configuration, that is normal until you change it in **Settings**.

## Open positions table {: #open-positions-table }

You can sort the table by clicking column headers.

- **Market** — what you are in, with a link to Polymarket when available.  
- **Side** — for example **No**.  
- **Size / Avg paid / Current** — how many shares and at what prices.  
- **Market value / PnL** — rough value and gain or loss using the latest price.  
- **Pot. Win** — what you would get if the position paid out fully in your favor.  
- **ETA** — time until the market **ends** (not a promise about when something fills).

## Recent activity {: #recent-trades--ledger }

This list is a **recent history** of what the bot tried and what happened—buys, sells, messages, and similar events. It is there so you can see the story without digging through raw logs.

For more on practice vs real money, see **[Trading modes](trading-modes.md)**. To change how aggressive or cautious the bot is, use **[Settings](settings.md)**.
