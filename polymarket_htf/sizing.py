from __future__ import annotations

import math


def trade_usd_from_capital(capital: float, *, max_stake_usd: float | None = 10.0) -> float:
    """
    Position size in USD: ``max(1, floor(0.10 * capital))``, capped by ``max_stake_usd`` and ``capital``.

    Default ``max_stake_usd=10`` matches live compounding spec (min \\$1 ticket, 10% floor, max \\$10/slice).
    Pass ``max_stake_usd=None`` to cap only by ``capital`` (no per-trade dollar ceiling).
    Below ``$1`` capital we return ``0`` (cannot place the minimum ticket).
    """
    if capital < 1.0:
        return 0.0
    raw = max(1, int(math.floor(capital * 0.10)))
    if max_stake_usd is None:
        return float(min(raw, capital))
    cap = float(max_stake_usd)
    if cap <= 0:
        return float(min(raw, capital))
    return float(min(raw, cap, capital))
