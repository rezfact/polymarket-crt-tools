"""
Environment-driven defaults for :mod:`scripts.month_crt_wss` (VPS / ``.env``).

Call :func:`polymarket_htf.config_env.load_dotenv_files` before reading these values.
Shell exports **override** ``.env`` (python-dotenv default). CLI flags override resolved defaults.

Prefix: ``CRT_MONTH_`` (see repository ``.env.example``).
"""
from __future__ import annotations

from pathlib import Path

from polymarket_htf.config_env import env_bool, env_float, env_int, env_optional_str, env_str


def _opt_float(name: str) -> float | None:
    v = env_optional_str(name)
    if v is None:
        return None
    return float(v)


def _opt_path(name: str) -> Path | None:
    v = env_optional_str(name)
    return Path(v) if v else None


def month_crt_wss_arg_defaults() -> dict[str, object]:
    """Keyword-style defaults for ``month_crt_wss`` argparse (after ``load_dotenv_files``)."""
    wss_out = env_optional_str("CRT_MONTH_WSS_OUT")
    crt_out = env_optional_str("CRT_MONTH_CRT_BARS_OUT")
    vis_dir = env_optional_str("CRT_MONTH_VISION_CACHE_DIR")
    return {
        "asset": env_str("CRT_MONTH_ASSET", "btc"),
        "start": env_optional_str("CRT_MONTH_START"),
        "end": env_optional_str("CRT_MONTH_END"),
        "price_source": env_str("CRT_MONTH_PRICE_SOURCE", "pyth"),
        "warmup_days": env_float("CRT_MONTH_WARMUP_DAYS", 45.0),
        "exec_interval": env_str("CRT_MONTH_EXEC_INTERVAL", "15m"),
        "context_interval": env_str("CRT_MONTH_CONTEXT_INTERVAL", "1h"),
        "range_lookback": env_int("CRT_MONTH_RANGE_LOOKBACK", 24),
        "crt_sweep_conflict": env_str("CRT_MONTH_CRT_SWEEP_CONFLICT", "skip"),
        "crt_preset": env_str("CRT_MONTH_CRT_PRESET", "default"),
        "crt_bars_out": Path(crt_out) if crt_out else None,
        "wss_out": Path(wss_out) if wss_out else Path("var/month_wss_sim.jsonl"),
        "wss_spot_source": env_str("CRT_MONTH_WSS_SPOT_SOURCE", "crt_15m"),
        "wss_preset": env_str("CRT_MONTH_WSS_PRESET", "default"),
        "slug_offset_steps": env_int("CRT_MONTH_SLUG_OFFSET_STEPS", 1),
        "entry_mode": env_str("CRT_MONTH_ENTRY_MODE", "until_buffer"),
        "entry_end_buffer_sec": env_float("CRT_MONTH_ENTRY_END_BUFFER_SEC", 90.0),
        "entry_first_minutes": env_float("CRT_MONTH_ENTRY_FIRST_MINUTES", 8.0),
        "max_gamma_outcome_dev": env_float("CRT_MONTH_MAX_GAMMA_OUTCOME_DEV", 0.12),
        "pullback_frac": env_float("CRT_MONTH_PULLBACK_FRAC", 0.0008),
        "toy_stake_usd": env_float("CRT_MONTH_TOY_STAKE_USD", 10.0),
        "toy_yes_mid": env_float("CRT_MONTH_TOY_YES_MID", 0.5),
        "toy_fee_roundtrip_bps": env_float("CRT_MONTH_TOY_FEE_ROUNDTRIP_BPS", 0.0),
        "toy_no_mid": _opt_float("CRT_MONTH_TOY_NO_MID"),
        "crt_htf_discount_max": _opt_float("CRT_MONTH_CRT_HTF_DISCOUNT_MAX"),
        "crt_htf_premium_min": _opt_float("CRT_MONTH_CRT_HTF_PREMIUM_MIN"),
        "crt_min_range_pct": _opt_float("CRT_MONTH_CRT_MIN_RANGE_PCT"),
        "crt_distribution_buffer_frac": _opt_float("CRT_MONTH_CRT_DISTRIBUTION_BUFFER_FRAC"),
        "vision_cache_dir": Path(vis_dir) if vis_dir else None,
        "vision_origin": env_optional_str("CRT_MONTH_VISION_ORIGIN"),
        "skip_wss": env_bool("CRT_MONTH_SKIP_WSS", False),
        "fetch_gamma": env_bool("CRT_MONTH_FETCH_GAMMA", False),
        "wss_nearmiss": env_bool("CRT_MONTH_WSS_NEARMISS", False),
        "wss_post_spot_sec": env_float("CRT_MONTH_WSS_POST_SPOT_SEC", 0.0),
        "wss_gamma_prices_at_fill": env_bool("CRT_MONTH_WSS_GAMMA_PRICES_AT_FILL", False),
        "wss_pnl_use_gamma_entry": env_bool("CRT_MONTH_WSS_PNL_USE_GAMMA_ENTRY", False),
        "late_fill_min_elapsed_sec": _opt_float("CRT_MONTH_LATE_FILL_MIN_ELAPSED_SEC"),
        "late_fill_max_remaining_sec": _opt_float("CRT_MONTH_LATE_FILL_MAX_REMAINING_SEC"),
        "max_retrace_frac": _opt_float("CRT_MONTH_MAX_RETRACE_FRAC"),
        "spot_vision": env_bool("CRT_MONTH_SPOT_VISION", False),
        "crt_no_htf_filter": env_bool("CRT_MONTH_CRT_NO_HTF_FILTER", False),
    }
