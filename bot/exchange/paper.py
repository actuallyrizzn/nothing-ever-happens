import threading
import time
from collections.abc import Callable
from typing import Any

from bot.models import (
    LimitOrderIntent,
    MarketOrderIntent,
    MarketRules,
    OpenOrder,
    OrderBookLevel,
    OrderBookSnapshot,
    OrderReadiness,
    OrderResult,
    Side,
    Trade,
)
from bot.time_utils import to_epoch_seconds

_MAX_PAPER_TRADES = 2000


class PaperExchangeClient:
    def __init__(
        self,
        initial_mid: float = 0.50,
        tick_size: float = 0.01,
        min_order_size: float = 1.0,
        initial_collateral_balance: float = 100.0,
        *,
        persist_save: Callable[[dict[str, Any]], None] | None = None,
        initial_state: dict[str, Any] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._persist_save = persist_save
        self.mid = initial_mid
        self._tick_size = tick_size
        self._min_order_size = min_order_size
        self._counter = 0
        self._open_orders: list[OpenOrder] = []
        self._trades: list[Trade] = []
        self._conditional_balances: dict[str, float] = {}
        self._collateral_balance = float(initial_collateral_balance)
        self._orders_by_id: dict[str, OpenOrder] = {}
        if initial_state:
            self._apply_state_unlocked(initial_state)

    def _persist_unlocked(self) -> None:
        if self._persist_save is None:
            return
        try:
            self._persist_save(self.export_state_unlocked())
        except Exception:
            pass

    def export_state_unlocked(self) -> dict[str, Any]:
        return {
            "version": 1,
            "mid": float(self.mid),
            "tick_size": float(self._tick_size),
            "min_order_size": float(self._min_order_size),
            "collateral_balance": float(self._collateral_balance),
            "conditional_balances": dict(self._conditional_balances),
            "counter": int(self._counter),
            "open_orders": [
                {
                    "order_id": o.order_id,
                    "token_id": o.token_id,
                    "side": o.side.value,
                    "price": float(o.price),
                    "size_matched": None if o.size_matched is None else float(o.size_matched),
                    "original_size": None if o.original_size is None else float(o.original_size),
                    "status": o.status or "",
                }
                for o in self._open_orders
            ],
            "trades": [
                {
                    "trade_id": t.trade_id,
                    "order_id": t.order_id,
                    "token_id": t.token_id,
                    "side": t.side.value,
                    "price": float(t.price),
                    "size": float(t.size),
                    "fee": float(t.fee),
                    "timestamp": t.timestamp,
                }
                for t in self._trades
            ],
        }

    def apply_state(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._apply_state_unlocked(data)
            self._persist_unlocked()

    def _apply_state_unlocked(self, data: dict[str, Any]) -> None:
        self.mid = float(data.get("mid", 0.5))
        self._tick_size = float(data.get("tick_size", 0.01))
        self._min_order_size = float(data.get("min_order_size", 1.0))
        self._collateral_balance = float(data.get("collateral_balance", 100.0))
        raw_cb = data.get("conditional_balances") or {}
        self._conditional_balances = {str(k): float(v) for k, v in raw_cb.items()} if isinstance(raw_cb, dict) else {}
        self._counter = int(data.get("counter", 0))
        self._open_orders = []
        self._orders_by_id = {}
        for row in data.get("open_orders") or []:
            if not isinstance(row, dict):
                continue
            o = OpenOrder(
                order_id=str(row["order_id"]),
                token_id=str(row["token_id"]),
                side=Side(str(row["side"])),
                price=float(row["price"]),
                size_matched=None if row.get("size_matched") is None else float(row["size_matched"]),
                original_size=None if row.get("original_size") is None else float(row["original_size"]),
                status=str(row.get("status") or "") or None,
            )
            self._open_orders.append(o)
            self._orders_by_id[o.order_id] = o
        self._trades = []
        for row in data.get("trades") or []:
            if not isinstance(row, dict):
                continue
            self._trades.append(
                Trade(
                    trade_id=str(row["trade_id"]),
                    order_id=str(row["order_id"]),
                    token_id=str(row["token_id"]),
                    side=Side(str(row["side"])),
                    price=float(row["price"]),
                    size=float(row["size"]),
                    fee=float(row.get("fee") or 0.0),
                    timestamp=row.get("timestamp"),
                )
            )
        if len(self._trades) > _MAX_PAPER_TRADES:
            self._trades = self._trades[-_MAX_PAPER_TRADES:]

    def set_mid(self, value: float) -> None:
        with self._lock:
            self.mid = value

    def bootstrap_live_trading(self, token_id: str | None = None) -> None:
        _ = token_id
        return None

    def get_mid_price(self, token_id: str) -> float:
        _ = token_id
        with self._lock:
            return self.mid

    def get_market_rules(self, token_id: str) -> MarketRules:
        _ = token_id
        with self._lock:
            return MarketRules(tick_size=self._tick_size, min_order_size=self._min_order_size)

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        with self._lock:
            bid = max(self.mid - self._tick_size, self._tick_size)
            ask = max(self.mid, self._tick_size)
            return OrderBookSnapshot(
                token_id=token_id,
                bids=(OrderBookLevel(price=bid, size=1_000.0),),
                asks=(OrderBookLevel(price=ask, size=1_000.0),),
                tick_size=self._tick_size,
                min_order_size=self._min_order_size,
                timestamp=int(time.time() * 1000),
            )

    def get_open_orders(self, token_id: str) -> list[OpenOrder]:
        with self._lock:
            return [o for o in self._open_orders if o.token_id == token_id]

    def get_order(self, order_id: str) -> OpenOrder | None:
        with self._lock:
            return self._orders_by_id.get(order_id)

    def place_limit_order(self, order: LimitOrderIntent) -> OrderResult:
        with self._lock:
            self._counter += 1
            oid = f"paper-{int(time.time())}-{self._counter}"
            snapshot = OpenOrder(
                order_id=oid,
                token_id=order.token_id,
                side=order.side,
                price=order.price,
                original_size=order.size,
                status="OPEN",
            )
            self._open_orders.append(snapshot)
            self._orders_by_id[oid] = snapshot
            self._persist_unlocked()
        return OrderResult(order_id=oid, status="simulated", raw={"order": order})

    def place_market_order(self, order: MarketOrderIntent) -> OrderResult:
        with self._lock:
            self._counter += 1
            oid = f"paper-{int(time.time())}-{self._counter}"
            execution_price = max(float(order.reference_price or self.mid), self._tick_size)
            if order.side.value == "SELL":
                size = min(order.amount, self._conditional_balances.get(order.token_id, 0.0))
                received_usd = size * execution_price
                self._conditional_balances[order.token_id] = max(
                    0.0, self._conditional_balances.get(order.token_id, 0.0) - size
                )
                self._collateral_balance += received_usd
                raw = {
                    "order": order,
                    "_market_price": execution_price,
                    "_buffered_price": execution_price,
                    "_fill_price": execution_price,
                    "makingAmount": str(size),
                    "takingAmount": str(received_usd),
                }
            else:
                spent_usd = min(float(order.amount), self._collateral_balance)
                size = (spent_usd / execution_price) if execution_price > 0 else 0.0
                self._conditional_balances[order.token_id] = (
                    self._conditional_balances.get(order.token_id, 0.0) + size
                )
                self._collateral_balance = max(0.0, self._collateral_balance - spent_usd)
                raw = {
                    "order": order,
                    "_market_price": execution_price,
                    "_buffered_price": execution_price,
                    "_fill_price": execution_price,
                    "makingAmount": str(spent_usd),
                    "takingAmount": str(size),
                }
            self._trades.append(
                Trade(
                    trade_id=f"{oid}-fill",
                    order_id=oid,
                    token_id=order.token_id,
                    side=order.side,
                    price=execution_price,
                    size=size,
                    timestamp=int(time.time()),
                )
            )
            if len(self._trades) > _MAX_PAPER_TRADES:
                self._trades = self._trades[-_MAX_PAPER_TRADES:]
            self._orders_by_id[oid] = OpenOrder(
                order_id=oid,
                token_id=order.token_id,
                side=order.side,
                price=execution_price,
                size_matched=size,
                original_size=size,
                status="matched",
            )
            self._persist_unlocked()
        return OrderResult(order_id=oid, status="matched", raw=raw)

    def warm_token_cache(self, token_id: str) -> None:
        _ = token_id

    def prepare_sell(self, token_id: str) -> bool:
        _ = token_id
        return True

    def get_conditional_balance(self, token_id: str) -> float:
        with self._lock:
            return float(self._conditional_balances.get(token_id, 0.0))

    def get_collateral_balance(self) -> float:
        with self._lock:
            return float(self._collateral_balance)

    def get_trades(self, token_id: str, after_timestamp: int | None = None) -> list[Trade]:
        with self._lock:
            trades = [t for t in self._trades if t.token_id == token_id]
            if after_timestamp is None:
                return list(trades)

            filtered: list[Trade] = []
            for trade in trades:
                ts = to_epoch_seconds(trade.timestamp)
                if ts is None or ts > after_timestamp:
                    filtered.append(trade)
            return filtered

    def check_order_readiness(self, order: LimitOrderIntent | MarketOrderIntent) -> OrderReadiness:
        _ = order
        return OrderReadiness(ready=True, reason="paper_exchange")

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            self._open_orders = [o for o in self._open_orders if o.order_id != order_id]
            self._orders_by_id.pop(order_id, None)
            self._persist_unlocked()
        return True

    def cancel_all(self) -> bool:
        with self._lock:
            self._open_orders.clear()
            self._orders_by_id.clear()
            self._persist_unlocked()
        return True
