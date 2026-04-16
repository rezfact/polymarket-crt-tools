"""Shared CLOB **BUY** limit planning (price/size from book + notional cap)."""
from __future__ import annotations

import math
from typing import Any


def _parse_midpoint(raw: object) -> float:
    if isinstance(raw, dict) and "mid" in raw:
        return float(raw["mid"])
    if isinstance(raw, (int, float)):
        return float(raw)
    return float(str(raw).strip())


def round_down_tick(price: float, tick: float) -> float:
    t = float(tick)
    if t <= 0:
        return float(price)
    return math.floor(float(price) / t + 1e-12) * t


def plan_buy_limit_notional(*, client: Any, token_id: str, max_usd: float) -> tuple[float, float, dict[str, Any]]:
    """
    Pick a GTC-style limit **BUY** price/size under ``max_usd`` notional (same strategy as ``clob_smoke``).

    Returns ``(price, size, meta)`` where ``meta`` includes mid, tick, min_order_size, best_bid.
    """
    mid = _parse_midpoint(client.get_midpoint(token_id))
    tick = float(client.get_tick_size(token_id))
    book = client.get_order_book(token_id)
    min_sz = float(book.min_order_size or "1")
    best_bid = float(book.bids[0].price) if book.bids else max(tick, mid - tick)
    price = round_down_tick(min(best_bid, mid), tick)
    if price < tick:
        price = tick
    if price > 1.0 - tick:
        price = 1.0 - tick
    max_sh = max_usd / price
    size = math.floor(max_sh * 1_000_000) / 1_000_000
    if size < min_sz:
        size = min_sz
    if price * size > max_usd + 1e-6:
        size = math.floor((max_usd / price) * 1_000_000) / 1_000_000
    if size < min_sz:
        raise ValueError(
            f"max_usd={max_usd} too small for min_order_size={min_sz} at price={price} "
            f"(need ≥ {min_sz * price:.2f} USDC)"
        )
    meta = {"mid": mid, "tick": tick, "min_order_size": min_sz, "best_bid": best_bid}
    return price, size, meta
