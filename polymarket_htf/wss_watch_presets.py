"""
Optional **sweet-spot watcher** bundles for :class:`polymarket_htf.watch_session.SweetSpotWatchParams`.

Use ``--wss-preset continuation`` on ``scripts/watch_sweet_spot.py`` for longer entry window /
milder pullback (research; pair with ``--diag-interval-sec`` on VPS).
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polymarket_htf.watch_session import SweetSpotWatchParams


def apply_sweet_spot_watch_preset(p: "SweetSpotWatchParams", preset: str) -> "SweetSpotWatchParams":
    """
    - ``default`` / empty: unchanged.
    - ``continuation``: smaller end buffer (more minutes tradable), slightly easier pullback,
      slightly looser Gamma outcome cap — aimed at more ``paper_fill`` vs timeout when spot is
      choppy (still not a guarantee).
    - ``late_window``: do not ``paper_fill`` until **≥600s** after ``T`` (last ~5m of a 15m window
      before your end-buffer); fewer fills, less time for spot to flip before resolution (research).
    - ``late_window_quality``: ``late_window`` + ``max_retrace_frac=0.0009`` to avoid
      chasing extended late moves.
    """
    name = (preset or "default").strip().lower()
    if name in ("", "default", "none"):
        return p
    if name == "continuation":
        return replace(
            p,
            pullback_frac=min(float(p.pullback_frac), 0.00055),
            entry_end_buffer_sec=min(float(p.entry_end_buffer_sec), 55.0),
            entry_first_minutes=max(float(p.entry_first_minutes), 14.0),
            max_gamma_outcome_deviation=max(float(p.max_gamma_outcome_deviation), 0.14),
        )
    if name == "late_window":
        return replace(
            p,
            late_fill_min_elapsed_sec=600.0,
        )
    if name == "late_window_quality":
        return replace(
            p,
            late_fill_min_elapsed_sec=600.0,
            max_retrace_frac=0.0009,
        )
    raise ValueError(
        f"unknown sweet-spot WSS preset {preset!r} (expected default, continuation, late_window, late_window_quality)"
    )
