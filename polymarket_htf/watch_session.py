"""
Paper **sweet-spot watcher** for one ``btc-updown-15m-*`` window at a time (C3 + O3 + E3/E5 + optional S3).

S3 (**signal revoke**): when enabled, a new CRT bar that disagrees with the armed side cancels the window.
**Sticky arm** (``SweetSpotWatchParams.sticky_arm``): skip S3 so the arm survives until ``paper_fill`` or timeout.

No orders — emits structured events for logging / benchmarking. Tune via :class:`SweetSpotWatchParams`.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from polymarket_htf.assets import binance_symbol, normalize_asset
from polymarket_htf.backtest_crt import share_settlement
from polymarket_htf.crt_wss_monthly import late_fill_timing_ok, wss_proxy_settlement_from_slice
from polymarket_htf.data import fetch_binance_klines_range
from polymarket_htf.chainlink_btc import fetch_chainlink_btc_usd
from polymarket_htf.crt_strategy import CRTParams, last_signal_completed_bar
from polymarket_htf.gamma import (
    build_updown_slug,
    exec_interval_to_polymarket_tf_minutes,
    fetch_event_by_slug,
    gamma_outcome_sum_deviation,
    gamma_side_price_gate,
    next_monitor_window_open_epoch,
)
from polymarket_htf.config_env import polygon_chainlink_btc_usd_feed, polygon_rpc_url


@dataclass
class SweetSpotWatchParams:
    """Benchmark-friendly knobs (arm A1/A2/A3/A5, T-window, E3/E5/E6, S3, C3, O3)."""

    asset: str = "btc"
    tf_minutes: int = 15
    price_source: Literal["binance", "pyth"] = "pyth"
    crt: CRTParams = field(default_factory=CRTParams)

    # A5 pre-warm (no trades; optional log only in runner)
    use_prearm: bool = True
    prearm_sec: float = 12.0

    # C3 slug selection
    slug_offset_steps: int = 1

    # T: when entries allowed inside [T, T_end)
    entry_mode: Literal["until_buffer", "first_minutes"] = "until_buffer"
    entry_end_buffer_sec: float = 90.0
    entry_first_minutes: float = 8.0

    # E3 Gamma outcome sanity
    max_gamma_outcome_deviation: float = 0.12
    require_gamma_active: bool = True
    # Optional: skip **arm** when Gamma mid for the target window is outside band (bad edge / lottery tickets).
    gamma_min_side_price: float | None = None
    gamma_max_side_price: float | None = None

    # E5 pullback vs session extreme (Chainlink); **fill** = pullback + entry window + Gamma (no fib).
    pullback_frac: float = 0.0008
    # Optional anti-chase gate: require ``retrace_frac <= max_retrace_frac`` at fill.
    max_retrace_frac: float | None = None

    # Optional late-only fills (see :func:`polymarket_htf.crt_wss_monthly.late_fill_timing_ok`).
    late_fill_min_elapsed_sec: float | None = None
    late_fill_max_remaining_sec: float | None = None

    # O3 Chainlink
    chainlink_stale_sec: float = 150.0
    polygon_rpc: str | None = None
    chainlink_feed: str | None = None

    # S3: if CRT flips side (or goes SKIP) on a **new** closed bar while a window is live, cancel the arm.
    enable_signal_revoke: bool = True
    # When True, **ignore S3** for this window: keep the armed side until ``paper_fill`` or ``timeout``.
    # Use for paper runs where bar-to-bar CRT flip is noise vs the Polymarket window you already armed.
    sticky_arm: bool = False

    # Optional arm filters (HTF on **signal bar**; same field as dryrun ``htf_rp_c1``).
    arm_require_htf_rp_ge: float | None = None  # UP: require ``htf_rp_c1 >=`` this
    arm_require_htf_rp_le: float | None = None  # DOWN: require ``htf_rp_c1 <=`` this

    # Periodic ``wss_diag`` rows during ``[T, T_end)`` (seconds between rows; ``None`` = off).
    diag_interval_sec: float | None = None

    # After ``paper_fill``: when ``now >= T_end + settlement_buffer_sec``, fetch Binance 1m slice
    # ``[T, T_end)`` and emit ``paper_settlement`` (first/last close proxy — not on-chain oracle).
    settlement_buffer_sec: float = 45.0
    settlement_stake_usd: float | None = None  # if set, add suggested PnL on ``paper_settlement``
    settlement_yes_mid: float = 0.5
    settlement_no_mid: float | None = None
    settlement_fee_roundtrip_bps: float = 0.0


def _entry_window_ok(*, now: float, T: float, T_end: float, p: SweetSpotWatchParams) -> bool:
    if now < T or now >= T_end - p.entry_end_buffer_sec:
        return False
    if p.entry_mode == "first_minutes":
        if now > T + p.entry_first_minutes * 60.0:
            return False
    return True


@dataclass
class _Monitor:
    slug: str
    side: str
    T: float
    T_end: float
    armed_bar_ts: str
    trend_up: bool
    ctx_high: float
    ctx_low: float


class SweetSpotWatchSession:
    """One in-flight monitor; call :meth:`tick` on a poll loop."""

    def __init__(self, params: SweetSpotWatchParams | None = None) -> None:
        self.p = params or SweetSpotWatchParams()
        a = normalize_asset(self.p.asset)
        self._asset = a
        tft = exec_interval_to_polymarket_tf_minutes(str(self.p.crt.exec_interval))
        if tft is None or tft != self.p.tf_minutes:
            raise ValueError(
                f"crt.exec_interval must match tf_minutes={self.p.tf_minutes} (got {self.p.crt.exec_interval!r})"
            )
        self._mon: _Monitor | None = None
        self._last_idle_sig_ts: str | None = None
        self._prearm_logged: bool = False
        self._session_spot_hi: float | None = None
        self._session_spot_lo: float | None = None
        self._pullback_ok: bool = False
        self._last_diag_ts: float = 0.0
        self._pending_settlements: list[dict[str, Any]] = []

    def _flush_pending_settlements(self, now: float, out: list[dict[str, Any]]) -> None:
        """Emit ``paper_settlement`` rows when window + buffer has passed."""
        if not self._pending_settlements:
            return
        buf = float(self.p.settlement_buffer_sec)
        kept: list[dict[str, Any]] = []
        for pen in self._pending_settlements:
            if now < float(pen["T_end"]) + buf:
                kept.append(pen)
                continue
            out.append(self._paper_settlement_row(pen))
        self._pending_settlements = kept

    def _paper_settlement_row(self, pen: dict[str, Any]) -> dict[str, Any]:
        slug = str(pen["slug"])
        side = str(pen["side"])
        T = int(pen["T"])
        T_end = int(pen["T_end"])
        t0 = pd.Timestamp(float(T), unit="s", tz="UTC")
        t1 = pd.Timestamp(float(T_end), unit="s", tz="UTC")
        pair = binance_symbol(self._asset)
        base: dict[str, Any] = {
            "kind": "paper_settlement",
            "slug": slug,
            "side": side,
            "T": T,
            "T_end": T_end,
            "settlement_proxy": "binance_1m_first_last_close",
            "fill_spot": pen.get("fill_spot"),
            "fill_chainlink_updated_at": pen.get("fill_chainlink_updated_at"),
        }
        try:
            win_df = fetch_binance_klines_range(pair, "1m", t0, t1)
        except Exception as e:  # noqa: BLE001 — Binance geo / network
            base["result"] = "proxy_error"
            base["error"] = str(e)
            base["error_type"] = type(e).__name__
            return base
        lab = wss_proxy_settlement_from_slice(win_df, side=side)
        base.update(lab)
        if lab.get("settlement_note") == "empty_spot_window":
            base["result"] = "no_klines"
            return base
        base["result"] = "ok"
        st_usd = self.p.settlement_stake_usd
        if (
            st_usd is not None
            and float(st_usd) > 0
            and not bool(lab.get("settlement_tie"))
            and lab.get("side_win") is not None
        ):
            fee_rt = float(self.p.settlement_fee_roundtrip_bps) / 10_000.0
            win = bool(lab["side_win"])
            st = share_settlement(
                usdc_spent=float(st_usd),
                win=win,
                side=side,
                yes_mid=float(self.p.settlement_yes_mid),
                no_mid=self.p.settlement_no_mid,
            )
            fee = float(st_usd) * fee_rt
            base["suggested_stake_usd"] = float(st_usd)
            base["suggested_entry_price"] = st.entry_price
            base["suggested_pnl_gross_usd"] = st.pnl_gross
            base["suggested_fees_usd"] = fee
            base["suggested_pnl_net_usd"] = st.pnl_gross - fee
        return base

    def _gamma_entry_gate_blocks(self, sig: dict[str, Any], out: list[dict[str, Any]]) -> bool:
        """If side-price gate is configured and fails, append ``skip_arm`` and return True."""
        p = self.p
        if p.gamma_min_side_price is None and p.gamma_max_side_price is None:
            return False
        ch = sig.get("ctx_high")
        cl = sig.get("ctx_low")
        close = sig.get("close")
        if ch is None or cl is None or close is None:
            return False
        next_wo = next_monitor_window_open_epoch(
            bar_open_utc=sig["timestamp"],
            tf_minutes=p.tf_minutes,
            slug_offset_steps=p.slug_offset_steps,
        )
        slug_try = build_updown_slug(self._asset, tf_minutes=p.tf_minutes, window_open_ts=int(next_wo))
        ev_try = fetch_event_by_slug(slug_try)
        if ev_try is None:
            out.append({"kind": "skip_arm", "reason": "gamma_404_precheck", "slug": slug_try})
            return True
        ok, det = gamma_side_price_gate(
            ev_try,
            side=str(sig["side"]),
            min_side_price=p.gamma_min_side_price,
            max_side_price=p.gamma_max_side_price,
        )
        if ok:
            return False
        out.append({"kind": "skip_arm", "reason": "gamma_side_price", "slug": slug_try, **det})
        return True

    def _arm_from_signal(self, sig: dict[str, Any], now: float, out: list[dict[str, Any]]) -> bool:
        p = self.p
        ch = sig.get("ctx_high")
        cl = sig.get("ctx_low")
        close = sig.get("close")
        if ch is None or cl is None or close is None:
            out.append({"kind": "skip_arm", "reason": "missing_ctx", "sig": sig})
            return False
        trend_up = float(close) >= (float(ch) + float(cl)) / 2.0
        next_wo = next_monitor_window_open_epoch(
            bar_open_utc=sig["timestamp"],
            tf_minutes=p.tf_minutes,
            slug_offset_steps=p.slug_offset_steps,
        )
        T = float(next_wo)
        T_end = T + float(p.tf_minutes * 60)
        slug = build_updown_slug(self._asset, tf_minutes=p.tf_minutes, window_open_ts=int(next_wo))
        side = str(sig["side"])
        rp_raw = sig.get("htf_rp_c1")
        if side == "UP" and p.arm_require_htf_rp_ge is not None:
            if rp_raw is None or not isinstance(rp_raw, (int, float)) or not math.isfinite(float(rp_raw)):
                out.append({"kind": "skip_arm", "reason": "htf_rp_missing_for_gate", "side": side})
                return False
            if float(rp_raw) < float(p.arm_require_htf_rp_ge):
                out.append(
                    {
                        "kind": "skip_arm",
                        "reason": "htf_rp_gate_up",
                        "htf_rp_c1": float(rp_raw),
                        "need_ge": float(p.arm_require_htf_rp_ge),
                    }
                )
                return False
        if side == "DOWN" and p.arm_require_htf_rp_le is not None:
            if rp_raw is None or not isinstance(rp_raw, (int, float)) or not math.isfinite(float(rp_raw)):
                out.append({"kind": "skip_arm", "reason": "htf_rp_missing_for_gate", "side": side})
                return False
            if float(rp_raw) > float(p.arm_require_htf_rp_le):
                out.append(
                    {
                        "kind": "skip_arm",
                        "reason": "htf_rp_gate_down",
                        "htf_rp_c1": float(rp_raw),
                        "need_le": float(p.arm_require_htf_rp_le),
                    }
                )
                return False

        self._mon = _Monitor(
            slug=slug,
            side=side,
            T=T,
            T_end=T_end,
            armed_bar_ts=str(sig["timestamp"]),
            trend_up=trend_up,
            ctx_high=float(ch),
            ctx_low=float(cl),
        )
        self._prearm_logged = False
        self._session_spot_hi = None
        self._session_spot_lo = None
        self._pullback_ok = False
        self._last_diag_ts = 0.0
        out.append(
            {
                "kind": "arm",
                "slug": slug,
                "side": side,
                "T": int(T),
                "T_end": int(T_end),
                "trend_up": trend_up,
                "ctx_high": float(ch),
                "ctx_low": float(cl),
                "bar_ts": sig["timestamp"],
                "sticky_arm": bool(p.sticky_arm),
            }
        )
        return True

    def tick(self, *, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else float(now)
        out: list[dict[str, Any]] = []
        self._flush_pending_settlements(now, out)
        sig = last_signal_completed_bar(
            self._asset,
            params=self.p.crt,
            price_source=self.p.price_source,
            now_ts=now,
        )
        ts_sig = sig.get("timestamp")

        if self._mon is None:
            if ts_sig is None:
                return out
            st = str(ts_sig)
            if st == self._last_idle_sig_ts:
                return out
            if sig.get("side") in ("UP", "DOWN"):
                if not self._gamma_entry_gate_blocks(sig, out):
                    self._arm_from_signal(sig, now, out)
            self._last_idle_sig_ts = st
            return out

        m = self._mon
        assert m is not None

        if now >= m.T_end:
            out.append({"kind": "skip", "reason": "timeout", "slug": m.slug})
            self._mon = None
            return out

        if self.p.use_prearm and m.T - self.p.prearm_sec <= now < m.T:
            if not self._prearm_logged:
                self._prearm_logged = True
                out.append({"kind": "prearm", "slug": m.slug, "T": int(m.T), "now": now})

        if now < m.T:
            return out

        # --- live window: S3 (optional), liquidity, pullback, fill ---
        revoke = self.p.enable_signal_revoke and not self.p.sticky_arm
        if revoke and ts_sig is not None and str(ts_sig) != m.armed_bar_ts:
            side2 = str(sig.get("side", "SKIP"))
            if side2 == "SKIP" or side2 != m.side:
                out.append(
                    {
                        "kind": "skip",
                        "reason": "signal_revoke",
                        "slug": m.slug,
                        "was": m.side,
                        "now_signal": side2,
                    }
                )
                self._mon = None
                return out

        try:
            cl = fetch_chainlink_btc_usd(
                rpc_url=self.p.polygon_rpc or polygon_rpc_url(),
                feed_address=self.p.chainlink_feed or polygon_chainlink_btc_usd_feed(),
            )
            spot = float(cl.price)
            if now - float(cl.updated_at) > self.p.chainlink_stale_sec:
                out.append({"kind": "warn", "reason": "chainlink_stale", "age_sec": now - float(cl.updated_at)})
        except Exception as e:  # noqa: BLE001 — surface RPC/ABI failures
            out.append({"kind": "warn", "reason": "chainlink_error", "error": str(e)})
            return out

        if self._session_spot_hi is None:
            self._session_spot_hi = spot
            self._session_spot_lo = spot
        else:
            self._session_spot_hi = max(self._session_spot_hi, spot)
            self._session_spot_lo = min(self._session_spot_lo, spot)

        if m.side == "UP" and self._session_spot_hi is not None:
            if spot <= self._session_spot_hi * (1.0 - self.p.pullback_frac):
                self._pullback_ok = True
        elif m.side == "DOWN" and self._session_spot_lo is not None:
            if spot >= self._session_spot_lo * (1.0 + self.p.pullback_frac):
                self._pullback_ok = True

        sh, slo = self._session_spot_hi, self._session_spot_lo
        retrace_frac = 0.0
        if m.side == "UP" and sh is not None and float(sh) > 0:
            retrace_frac = max(0.0, (float(sh) - spot) / float(sh))
        elif m.side == "DOWN" and slo is not None and float(slo) > 0:
            retrace_frac = max(0.0, (spot - float(slo)) / float(slo))

        win_ok = _entry_window_ok(now=now, T=m.T, T_end=m.T_end, p=self.p)
        late_ok = late_fill_timing_ok(
            now=now,
            T=m.T,
            T_end=m.T_end,
            min_elapsed=self.p.late_fill_min_elapsed_sec,
            max_remaining=self.p.late_fill_max_remaining_sec,
        )
        iv = self.p.diag_interval_sec
        if iv is not None and float(iv) > 0 and now >= m.T and now < m.T_end:
            if self._last_diag_ts == 0.0 or now - self._last_diag_ts >= float(iv):
                ev_d = fetch_event_by_slug(m.slug)
                dev_d = gamma_outcome_sum_deviation(ev_d) if ev_d is not None else None
                gam_ok: bool | None = None
                gam_reason: str | None = None
                if ev_d is None:
                    gam_reason = "gamma_404"
                elif self.p.require_gamma_active and (not ev_d.get("active") or ev_d.get("closed")):
                    gam_ok = False
                    gam_reason = "gamma_inactive"
                else:
                    gam_ok = True
                dev_ok = None if dev_d is None else (dev_d <= self.p.max_gamma_outcome_deviation)
                out.append(
                    {
                        "kind": "wss_diag",
                        "slug": m.slug,
                        "side": m.side,
                        "now": now,
                        "secs_to_T_end": float(m.T_end - now),
                        "entry_window_ok": win_ok,
                        "late_fill_ok": bool(late_ok),
                        "secs_since_T": float(now - m.T),
                        "pullback_ok": bool(self._pullback_ok),
                        "retrace_cap_ok": (
                            True
                            if self.p.max_retrace_frac is None
                            else (float(retrace_frac) <= float(self.p.max_retrace_frac))
                        ),
                        "session_spot_hi": float(sh) if sh is not None else None,
                        "session_spot_lo": float(slo) if slo is not None else None,
                        "retrace_frac": float(retrace_frac),
                        "spot": spot,
                        "gamma_dev": dev_d,
                        "gamma_dev_ok": dev_ok,
                        "gamma_active_ok": gam_ok,
                        "gamma_reason": gam_reason,
                        "crt_side": sig.get("side"),
                        "crt_htf_rp_c1": sig.get("htf_rp_c1"),
                        "crt_bar_ts": sig.get("timestamp"),
                        "armed_bar_ts": m.armed_bar_ts,
                        "chainlink_age_sec": float(now - float(cl.updated_at)),
                    }
                )
                self._last_diag_ts = now

        if not win_ok:
            return out

        ev = fetch_event_by_slug(m.slug)
        if ev is None:
            out.append({"kind": "warn", "reason": "gamma_404", "slug": m.slug})
            return out
        if self.p.require_gamma_active and (not ev.get("active") or ev.get("closed")):
            out.append({"kind": "warn", "reason": "gamma_inactive", "slug": m.slug})
            return out

        dev = gamma_outcome_sum_deviation(ev)
        if dev is None:
            return out
        if dev > self.p.max_gamma_outcome_deviation:
            return out

        if not self._pullback_ok:
            return out
        if self.p.max_retrace_frac is not None and float(retrace_frac) > float(self.p.max_retrace_frac):
            return out

        if not late_ok:
            return out

        self._pending_settlements.append(
            {
                "slug": m.slug,
                "side": m.side,
                "T": int(m.T),
                "T_end": int(m.T_end),
                "fill_spot": spot,
                "fill_chainlink_updated_at": cl.updated_at,
            }
        )
        out.append(
            {
                "kind": "paper_fill",
                "slug": m.slug,
                "side": m.side,
                "T": int(m.T),
                "T_end": int(m.T_end),
                "spot": spot,
                "chainlink_updated_at": cl.updated_at,
                "retrace_frac": float(retrace_frac),
            }
        )
        self._mon = None
        return out
