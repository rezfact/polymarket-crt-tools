"""
**Premium return** take-profit ladder: when mark moves up vs average entry by X%,
sell a fraction of **remaining** shares (Polymarket YES/NO mid in (0,1)).

This module is **pure planning** + JSON state. **CLOB sell orders** are not implemented
in this repo yet; use ``scripts/watch_take_profit.py`` in dry-run or wire
``on_planned_exit`` to py-clob-client when ready.

For **CRT backtests**, :func:`simulate_tp_ladder_on_bridge` walks a linear synthetic path
from fill to the toy terminal (see ``scripts/backtest.py --tp-tiers``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


def premium_return_pct(avg_entry: float, mark: float) -> float:
    """Percent move on premium: ``(mark - entry) / entry * 100``."""
    if avg_entry <= 0:
        return float("nan")
    return (mark - avg_entry) / avg_entry * 100.0


def parse_tiers_spec(spec: str) -> list[tuple[float, float]]:
    """
    ``"500:0.5,1000:1"`` → ascending by threshold:
    at +500% premium return sell 50% of **remaining** size; at +1000% sell 100% of remaining.

    Fractions are in (0, 1]; ``1`` = all remaining at that tier.
    """
    s = spec.strip()
    if not s:
        raise ValueError("empty tiers spec")
    pairs: list[tuple[float, float]] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\s*([0-9.+-eE]+)\s*:\s*([0-9.]+)\s*$", part)
        if not m:
            raise ValueError(f"bad tier segment (want THRESHOLD_PCT:FRACTION): {part!r}")
        thr = float(m.group(1))
        frac = float(m.group(2))
        if thr < 0:
            raise ValueError(f"threshold must be >= 0: {thr}")
        if not (0.0 < frac <= 1.0):
            raise ValueError(f"fraction must be in (0, 1]: {frac}")
        pairs.append((thr, frac))
    if not pairs:
        raise ValueError("no tiers parsed")
    pairs.sort(key=lambda x: x[0])
    return pairs


@dataclass(frozen=True)
class PlannedExit:
    tier_index: int
    threshold_pct: float
    sell_fraction: float
    shares: float
    premium_return_pct: float


def plan_ladder_exits(
    *,
    avg_entry: float,
    mark: float,
    position_size: float,
    tiers: Sequence[tuple[float, float]],
    fired: Sequence[bool],
) -> tuple[list[PlannedExit], list[bool]]:
    """
    Given **current** size and which tiers already fired, return new planned sells and updated fired flags.

    Multiple tiers can fire in one evaluation if return is already above later thresholds
    (sequential: each tier sells a fraction of **remaining** after previous tiers in this call).
    """
    tier_list = list(tiers)
    if len(fired) != len(tier_list):
        raise ValueError("fired length must match tiers length")
    ret = premium_return_pct(avg_entry, mark)
    remaining = max(0.0, float(position_size))
    new_fired = list(fired)
    planned: list[PlannedExit] = []

    for i, (thr, frac) in enumerate(tier_list):
        if new_fired[i]:
            continue
        if remaining <= 0:
            break
        if ret != ret:  # nan
            break
        if ret < thr:
            break
        raw_sh = remaining * frac
        shares = max(0.0, raw_sh)
        if shares <= 0:
            new_fired[i] = True
            continue
        planned.append(
            PlannedExit(
                tier_index=i,
                threshold_pct=thr,
                sell_fraction=frac,
                shares=shares,
                premium_return_pct=ret,
            )
        )
        remaining -= shares
        new_fired[i] = True

    return planned, new_fired


@dataclass(frozen=True)
class TpBridgeSimResult:
    """Outcome of :func:`simulate_tp_ladder_on_bridge` (research / backtest)."""

    pnl_gross: float
    cash_from_sales: float
    final_redemption_usd: float
    remaining_shares_end: float
    events: list[dict[str, Any]]
    fired: list[bool]


def linear_bridge_marks(entry: float, terminal: float, *, steps: int) -> list[float]:
    """Inclusive linear path ``entry → terminal`` (``steps`` ≥ 2 points)."""
    n = max(2, int(steps))
    e, t = float(entry), float(terminal)
    if n == 2:
        return [e, t]
    return [e + (t - e) * j / (n - 1) for j in range(n)]


def simulate_tp_ladder_on_bridge(
    *,
    usdc_spent: float,
    entry_price: float,
    shares: float,
    terminal_price: float,
    tiers: Sequence[tuple[float, float]],
    bridge_steps: int = 64,
) -> TpBridgeSimResult:
    """
    Walk a **synthetic** mark path (linear from fill to settlement 0/1), evaluating the
    ladder at each point. Partial sells credit ``mark * shares``; any remaining shares
    redeem at ``terminal_price``.

    **Not** a replay of historical Polymarket mids — only a backtest hook to compare
    hold-to-resolution vs staged exits under the same toy win/loss label.
    """
    tier_list = list(tiers)
    marks = linear_bridge_marks(entry_price, terminal_price, steps=bridge_steps)
    remaining = max(0.0, float(shares))
    fired = [False] * len(tier_list)
    events: list[dict[str, Any]] = []
    cash_sales = 0.0
    for m in marks:
        planned, fired = plan_ladder_exits(
            avg_entry=entry_price,
            mark=m,
            position_size=remaining,
            tiers=tier_list,
            fired=fired,
        )
        for pl in planned:
            cash_sales += pl.shares * m
            remaining -= pl.shares
            events.append(
                {
                    "mark": m,
                    "shares": pl.shares,
                    "tier_index": pl.tier_index,
                    "threshold_pct": pl.threshold_pct,
                    "premium_return_pct": pl.premium_return_pct,
                }
            )
    final_red = remaining * float(terminal_price)
    cash_total = cash_sales + final_red
    pnl_gross = cash_total - float(usdc_spent)
    return TpBridgeSimResult(
        pnl_gross=pnl_gross,
        cash_from_sales=cash_sales,
        final_redemption_usd=final_red,
        remaining_shares_end=remaining,
        events=events,
        fired=list(fired),
    )


def position_key(pos: dict[str, Any]) -> str:
    cid = str(pos.get("conditionId") or pos.get("condition_id") or "").strip()
    out = str(pos.get("outcome") or pos.get("outcomeName") or "").strip()
    oi = pos.get("outcomeIndex")
    if oi is not None and str(oi).strip() != "":
        return f"{cid}|{out}|{oi}".lower()
    return f"{cid}|{out}".lower()


def position_avg_entry(pos: dict[str, Any]) -> float | None:
    for k in ("avgPrice", "averagePrice", "avg_price"):
        v = pos.get(k)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x > 0:
            return x
    return None


def position_mark(pos: dict[str, Any]) -> float | None:
    for k in ("curPrice", "currentPrice", "price", "markPrice"):
        v = pos.get(k)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if 0.0 < x < 1.0:
            return x
    return None


def load_ladder_state(path: Path) -> dict[str, list[bool]]:
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[bool]] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, list) and all(isinstance(b, bool) for b in v):
            out[k] = list(v)
    return out


def save_ladder_state(path: Path, state: dict[str, list[bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def merge_fired_for_tiers(state: dict[str, list[bool]], key: str, n_tiers: int, new_fired: list[bool]) -> None:
    state[key] = list(new_fired[:n_tiers])
