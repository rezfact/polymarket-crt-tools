"""Optional Polymarket CLOB **collateral** (USDC) balance read for live guards."""
from __future__ import annotations

from typing import Any


def _collateral_raw_to_usd(v: float) -> float:
    """Polymarket CLOB often returns USDC collateral as an integer-style count of micro-units (1e6)."""
    if v >= 500_000.0:
        return v / 1_000_000.0
    return v


def clob_collateral_balance_usd(client: Any) -> float | None:
    """
    Return tradable **collateral** balance in USDC (best effort), or ``None`` if unavailable.

    Uses ``py_clob_client`` ``get_balance_allowance`` with ``AssetType.COLLATERAL``.
    """
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        r = client.get_balance_allowance(params)
        if isinstance(r, dict):
            for k in ("balance", "available", "availableBalance"):
                if k in r and r[k] is not None:
                    return _collateral_raw_to_usd(float(r[k]))
        if isinstance(r, (int, float)):
            return _collateral_raw_to_usd(float(r))
        if isinstance(r, str):
            return _collateral_raw_to_usd(float(r.strip()))
    except Exception:
        return None
    return None
