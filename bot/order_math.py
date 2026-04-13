"""Shared probability clamp and submitted-price rules for CLOB market BUY orders.

Used by live exchange code and the backtest engine so slippage / cap math stays aligned.
"""


def clamp_probability(price: float) -> float:
    """Clamp to Polymarket-style probability bounds (same as legacy _clamp_probability)."""
    return max(0.01, min(0.99, float(price)))


def submitted_buy_price(
    reference_price: float,
    *,
    max_entry_price: float,
    allowed_slippage: float,
) -> float:
    """Price passed to create_market_order for a BUY when using a price cap (Nothing Happens).

    When ``max_entry_price > 0`` (always true for validated NothingHappensConfig), the
    buffered limit is ``clamp(max_entry_price)``. Otherwise it is
    ``clamp(reference_price + allowed_slippage)``.
    """
    if max_entry_price > 0:
        return clamp_probability(max_entry_price)
    return clamp_probability(float(reference_price) + float(allowed_slippage))


def market_buy_buffered_price(
    *,
    reference_price: float,
    allowed_slippage: float,
    price_cap: float | None,
) -> float:
    """Mirror ``PolymarketClobExchangeClient.place_market_order`` BUY limit selection."""
    if price_cap is not None:
        return clamp_probability(price_cap)
    return clamp_probability(float(reference_price) + float(allowed_slippage))
