# Backtest golden fixtures (plan §11 Phase 1)

Synthetic expectations are built in **`tests/test_backtest_golden.py`** (network-off).

| Case | Config | Series | Expected `t_first` |
| --- | --- | --- | --- |
| `golden_t_first_p1` | `max_entry_price=0.5`, `half_spread=0` | `(T, 0.60)`, `(T+60, 0.40)` | `T+60` (first bar fails `no_ask <= max_entry`) |
| `void_resolution_excludes_pnl` | defaults | single bar in range | entered, PnL excluded from sum (`resolution_status=void`) |

Timestamps use Unix seconds in the `1_700_000_000` range so **`validate`** accepts them.
