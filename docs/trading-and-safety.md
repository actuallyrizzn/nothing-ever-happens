# Trading & safety

Nothing Ever Happens can run in **paper** mode (simulated exchange) or **live** mode (real Polymarket CLOB), subject to explicit safety gates.

## Paper vs live {: #paper-vs-live }

| Mode | Exchange client | Real orders |
| --- | --- | --- |
| Paper (default) | `PaperExchangeClient` | **No** — simulated book, balances, and fills. |
| Live | `PolymarketClobExchangeClient` | **Yes** — when all three live flags are set (below). |

Public market **discovery** (Gamma / data APIs) still runs for scanning in both modes; only **order placement** and **wallet-backed reads** go through the chosen exchange client.

## The three live gates {: #three-live-gates }

Real order transmission requires **all** of:

```text
BOT_MODE=live
LIVE_TRADING_ENABLED=true
DRY_RUN=false
```

If **any** is missing or false-ish, the bot stays on the paper client regardless of keys present.

## Required secrets (live) {: #secrets-live }

- **`PRIVATE_KEY`** — signing key for the CLOB client (format per `py-clob-client` / Polymarket account type).  
- **`FUNDER_ADDRESS`** — required when `signature_type` is **1** or **2** (proxy / delegated wallet flows).  
- **`POLYGON_RPC_URL`** — HTTPS JSON-RPC for Polygon; used for on-chain steps (e.g. proxy approvals, redeemer). Required for **live + signature_type 2 + funder** in typical proxy setups.

## Signature types {: #signature-types }

Configured via `PM_CONNECTION_SIGNATURE_TYPE` (or `config.json` → overridden by DB):

| Value | Role |
| --- | --- |
| `0` | EOA signs directly; funder usually omitted. |
| `1`, `2` | Proxy / delegated flows — **funder** is the Polymarket proxy address. |

Mismatch between your **actual** Polymarket login method and `signature_type` is a common source of auth or order errors.

## SQLite in live mode {: #sqlite-live }

Live mode **requires** a configured SQLite URL/path so order recovery and ledger tables exist. See `bot/main` (`_validate_live_runtime`).

## Related docs

- [Runtime settings](runtime-settings.md)  
- [Strategy parameters](strategy-parameters.md)  
- [Risk controls](risk-controls.md)
