from __future__ import annotations

_ASSETS: dict[str, dict[str, str]] = {
    "btc": {"slug_token": "btc", "binance": "BTCUSDT"},
    "eth": {"slug_token": "eth", "binance": "ETHUSDT"},
    "sol": {"slug_token": "sol", "binance": "SOLUSDT"},
}


def normalize_asset(key: str) -> str:
    k = (key or "btc").lower().strip()
    if k not in _ASSETS:
        raise ValueError(f"unknown asset {key!r}; use one of: {sorted(_ASSETS)}")
    return k


def binance_symbol(asset: str) -> str:
    return _ASSETS[normalize_asset(asset)]["binance"]


def pyth_tv_symbol_for_binance_pair(pair: str) -> str:
    """Pyth Benchmarks TV symbol for a Binance USDT spot pair (e.g. ``BTCUSDT`` → ``Crypto.BTC/USD``)."""
    u = (pair or "").upper().strip()
    for row in _ASSETS.values():
        if row["binance"].upper() == u:
            base = row["binance"][:-4]  # strip USDT
            return f"Crypto.{base}/USD"
    raise ValueError(f"no Pyth TV mapping for Binance pair {pair!r}; supported: {[r['binance'] for r in _ASSETS.values()]}")


def slug_token(asset: str) -> str:
    return _ASSETS[normalize_asset(asset)]["slug_token"]


def supported_assets() -> tuple[str, ...]:
    return tuple(sorted(_ASSETS))
