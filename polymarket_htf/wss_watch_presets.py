"""
Optional **sweet-spot watcher** bundles for :class:`polymarket_htf.watch_session.SweetSpotWatchParams`.

Use ``--wss-preset continuation`` on ``scripts/watch_sweet_spot.py`` for slightly wider fib / longer
entry window / milder pullback (research; pair with ``--diag-interval-sec`` on VPS).
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polymarket_htf.watch_session import SweetSpotWatchParams


def apply_sweet_spot_watch_preset(p: "SweetSpotWatchParams", preset: str) -> "SweetSpotWatchParams":
    """
    - ``default`` / empty: unchanged.
    - ``continuation``: wider fib band, smaller end buffer (more minutes tradable), slightly
      easier pullback, slightly looser Gamma outcome cap — aimed at more ``paper_fill`` vs timeout
      when spot is choppy (still not a guarantee).
    """
    name = (preset or "default").strip().lower()
    if name in ("", "default", "none"):
        return p
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
    raise ValueError(f"unknown sweet-spot WSS preset {preset!r} (expected default, continuation)")
