"""
Optional **WSS month sim** bundles for :func:`polymarket_htf.crt_wss_monthly.simulate_wss_window`.

``--wss-spot-source crt_15m`` feeds at most a few OHLC points per 15m Polymarket window, so the
default pullback / fib gates rarely fire (mostly ``timeout``). ``coarse_spot`` relaxes those gates
for **research-only** stress tests — prefer ``binance_1m`` when reachable for realistic fills.
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polymarket_htf.crt_wss_monthly import WssMonthSimParams


def apply_wss_month_preset(p: "WssMonthSimParams", preset: str) -> "WssMonthSimParams":
    """
    Return a copy of ``p`` with a named preset applied **on top** of caller-built params.

    - ``default``: unchanged.
    - ``coarse_spot``: smaller pullback requirement, slightly wider fib band, shorter end buffer so
      coarse feeds (e.g. CRT 15m closes) can occasionally register ``paper_fill``. Does **not**
      replace proper 1m spot.
    - ``continuation``: aligns with :func:`polymarket_htf.wss_watch_presets.apply_sweet_spot_watch_preset`
      ``continuation`` (wider fib, milder pullback, more entry minutes, looser Gamma cap) for local
      month runs vs ``watch_sweet_spot`` on VPS.
    """
    name = (preset or "default").strip().lower()
    if name in ("", "default", "none"):
        return p
    if name == "coarse_spot":
        # Widen fib band in *retracement space*: smaller fib_lo + larger fib_hi → larger (fib_hi - fib_lo).
        return replace(
            p,
            pullback_frac=min(float(p.pullback_frac), 0.00015),
            fib_lo=min(float(p.fib_lo), 0.55),
            fib_hi=max(float(p.fib_hi), 0.82),
            entry_end_buffer_sec=min(float(p.entry_end_buffer_sec), 45.0),
            entry_first_minutes=max(float(p.entry_first_minutes), 12.0),
        )
    if name == "continuation":
        return replace(
            p,
            pullback_frac=min(float(p.pullback_frac), 0.00055),
            fib_lo=min(float(p.fib_lo), 0.56),
            fib_hi=max(float(p.fib_hi), 0.83),
            entry_end_buffer_sec=min(float(p.entry_end_buffer_sec), 55.0),
            entry_first_minutes=max(float(p.entry_first_minutes), 14.0),
            max_gamma_outcome_deviation=max(float(p.max_gamma_outcome_deviation), 0.14),
        )
    raise ValueError(f"unknown WSS month preset {preset!r} (expected default, coarse_spot, continuation)")
