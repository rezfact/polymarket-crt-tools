"""
Historical **CRT signal** histograms and a compact **lessons** document for research.

The mechanical classifier in :func:`polymarket_htf.crt_strategy.crt_signal_row` only ever
returns ``UP`` / ``DOWN`` with **two** reason strings (bull sweep + inside, bear sweep + inside).
All other outcomes are ``SKIP`` with various reasons. "Rare special patterns" in the **directional**
sense would require **new** rules in ``crt_signal_row``, not mining new reason labels from history.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

# Canonical directional reasons (must match crt_strategy.crt_signal_row).
KNOWN_UP_REASON = "crt_amd_bull_sweep_crl_c3_inside"
KNOWN_DOWN_REASON = "crt_amd_bear_sweep_crh_c3_inside"


def summarize_side_reason(
    sides: list[str],
    reasons: list[str],
    *,
    bar_timestamps: list[str] | None = None,
) -> dict[str, Any]:
    if len(sides) != len(reasons):
        raise ValueError("sides and reasons must have the same length")
    n = len(sides)
    c_side = Counter(sides)
    c_reason = Counter(reasons)

    up_reasons = {r for s, r in zip(sides, reasons) if s == "UP"}
    down_reasons = {r for s, r in zip(sides, reasons) if s == "DOWN"}
    anomaly_up = sorted(up_reasons - {KNOWN_UP_REASON})
    anomaly_down = sorted(down_reasons - {KNOWN_DOWN_REASON})

    skip_reasons = [r for s, r in zip(sides, reasons) if s == "SKIP"]
    c_skip = Counter(skip_reasons)
    n_skip = sum(c_skip.values()) or 1

    skip_rarity = [
        {"reason": r, "count": c, "pct_of_skip": round(100.0 * c / n_skip, 4)}
        for r, c in sorted(c_skip.items(), key=lambda x: (x[1], x[0]))
    ]

    rare_skip_threshold = max(10, int(0.001 * n_skip) + 1)
    rare_skips = [x for x in skip_rarity if x["count"] < rare_skip_threshold and x["count"] > 0]

    by_reason_sorted = dict(sorted(c_reason.items(), key=lambda x: (-x[1], str(x[0]))))
    out: dict[str, Any] = {
        "bars": n,
        "counts_by_side": dict(c_side),
        "counts_by_reason": by_reason_sorted,
        "direction_reasons_observed": {
            "UP": sorted(up_reasons),
            "DOWN": sorted(down_reasons),
            "anomaly_if_noncanonical": {
                "UP": anomaly_up,
                "DOWN": anomaly_down,
            },
        },
        "skip_reason_rarity_sorted": skip_rarity,
        "rare_skip_reasons": rare_skips,
        "classifier_note": (
            "UP/DOWN reasons are fixed to two templates in crt_signal_row; "
            "rarity applies to SKIP/warmup/auxiliary reasons unless code adds new directions."
        ),
    }
    if bar_timestamps is not None and len(bar_timestamps) == n:
        out["first_bar"] = bar_timestamps[0]
        out["last_bar"] = bar_timestamps[-1]
    return out


def _finite_floats(xs: list[Any]) -> list[float]:
    out: list[float] = []
    for x in xs:
        if x is None:
            continue
        try:
            v = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append(v)
    return out


def _quantiles(vals: list[float], qs: tuple[float, ...] = (0.1, 0.5, 0.9)) -> dict[str, float | None]:
    if len(vals) < 5:
        return {f"p{int(q * 100)}": None for q in qs}
    s = pd.Series(vals, dtype="float64")
    return {f"p{int(q * 100)}": float(s.quantile(q)) for q in qs}


def enrich_with_bar_context(
    *,
    sides: list[str],
    reasons: list[str],
    index: pd.DatetimeIndex | list[pd.Timestamp] | list[str],
    htf_rp_c1: list[Any] | pd.Series | None = None,
    c1_range_pct: list[Any] | pd.Series | None = None,
    sweep_below_crl: list[Any] | pd.Series | None = None,
    sweep_above_crh: list[Any] | pd.Series | None = None,
    c3_inside_c1: list[Any] | pd.Series | None = None,
) -> dict[str, Any]:
    """
    Per-bar context aligned with ``sides`` / ``reasons`` (same length), for strategy research.

    Adds: HTF / range quantiles by reason, UTC hour-of-day for signals, reason→next-side transitions.
    """
    n = len(sides)
    if len(reasons) != n:
        raise ValueError("reasons length must match sides")
    idx = pd.DatetimeIndex(pd.to_datetime(index, utc=True)) if not isinstance(index, pd.DatetimeIndex) else index

    def _series(x: list[Any] | pd.Series | None) -> list[Any]:
        if x is None:
            return [None] * n
        if isinstance(x, pd.Series):
            return [x.iloc[i] if i < len(x) else None for i in range(n)]
        if len(x) != n:
            raise ValueError("context series length must match sides")
        return list(x)

    htf = _series(htf_rp_c1)
    rp = _series(c1_range_pct)
    sb = _series(sweep_below_crl)
    sa = _series(sweep_above_crh)
    ins = _series(c3_inside_c1)

    by_reason_htf: dict[str, dict[str, float | None]] = {}
    by_reason_rp: dict[str, dict[str, float | None]] = {}
    for reason in sorted(set(reasons)):
        mask_htf = [reasons[i] == reason for i in range(n)]
        hvals = _finite_floats([htf[i] for i in range(n) if mask_htf[i]])
        rvals = _finite_floats([rp[i] for i in range(n) if mask_htf[i]])
        by_reason_htf[reason] = _quantiles(hvals)
        by_reason_rp[reason] = _quantiles(rvals)

    by_side_htf = {}
    for side in ("UP", "DOWN", "SKIP"):
        mask = [sides[i] == side for i in range(n)]
        hvals = _finite_floats([htf[i] for i in range(n) if mask[i]])
        by_side_htf[side] = _quantiles(hvals)

    sig_hour = Counter()
    sig_dow = Counter()
    for i in range(n):
        if sides[i] not in ("UP", "DOWN"):
            continue
        ts = idx[i]
        sig_hour[int(ts.hour)] += 1
        sig_dow[int(ts.dayofweek)] += 1

    trans = Counter()
    for i in range(n - 1):
        trans[(reasons[i], sides[i + 1])] += 1
    trans_top = [
        {"prev_reason": a, "next_side": b, "count": c}
        for (a, b), c in trans.most_common(40)
    ]

    after_skip: dict[str, Counter[str]] = {}
    for i in range(n - 1):
        if sides[i] != "SKIP":
            continue
        r = reasons[i]
        after_skip.setdefault(r, Counter())[sides[i + 1]] += 1
    after_skip_json = {k: dict(v) for k, v in sorted(after_skip.items())}

    def _mean_bool(series: list[Any]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for label, ser in (("sweep_below_crl", sb), ("sweep_above_crh", sa), ("c3_inside_c1", ins)):
            hits = 0
            tot = 0
            for i in range(n):
                v = ser[i]
                if v is None or (isinstance(v, float) and not math.isfinite(v)):
                    continue
                tot += 1
                if bool(v):
                    hits += 1
            out[label] = (hits / tot) if tot else None
        return out

    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "htf_rp_c1_quantiles_by_reason": by_reason_htf,
        "c1_range_pct_quantiles_by_reason": by_reason_rp,
        "htf_rp_c1_quantiles_by_side": by_side_htf,
        "signal_counts_by_hour_utc": {str(h): sig_hour[h] for h in range(24)},
        "signal_counts_by_weekday_utc": {dow_names[d]: sig_dow[d] for d in range(7)},
        "prev_reason_to_next_side_top": trans_top,
        "after_skip_next_side_counts": after_skip_json,
        "row_truth_rates_all_bars": _mean_bool(sb),
    }


def _pct(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 3)


def derive_tuning_dig(
    summary: dict[str, Any],
    enriched: dict[str, Any] | None,
    crt_params: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Turn skip mix + optional ``enriched`` block into **actionable** tuning notes.

    Does not add new ``crt_signal_row`` direction templates; it recommends gate / preset moves
    that historically change SKIP → AMD-valid rows.
    """
    n = int(summary.get("bars") or 0)
    cr = summary.get("counts_by_reason") or {}
    cs = summary.get("counts_by_side") or {}
    if not isinstance(cr, dict) or n <= 0:
        return {"dig_version": 1, "premise": "insufficient summary", "suggested_ab_runs": []}

    skip_n = int(cs.get("SKIP", 0)) if isinstance(cs, dict) else 0
    up_n = int(cs.get("UP", 0)) if isinstance(cs, dict) else 0
    down_n = int(cs.get("DOWN", 0)) if isinstance(cs, dict) else 0

    def _c(key: str) -> int:
        return int(cr.get(key, 0)) if isinstance(cr, dict) else 0

    dist = _c("crt_no_distribution_inside")
    manip = _c("crt_no_manipulation")
    tight = _c("c1_range_too_tight")
    conflict = _c("crt_sweep_conflict")

    skip_mix = {
        "crt_no_distribution_inside_pct_of_bars": _pct(dist, n),
        "crt_no_manipulation_pct_of_bars": _pct(manip, n),
        "c1_range_too_tight_pct_of_bars": _pct(tight, n),
        "crt_sweep_conflict_pct_of_bars": _pct(conflict, n),
        "directional_pct_of_bars": _pct(up_n + down_n, n),
    }

    ranked_skips = sorted(
        [(k, int(v)) for k, v in cr.items() if k not in (KNOWN_UP_REASON, KNOWN_DOWN_REASON) and int(v) > 0],
        key=lambda x: -x[1],
    )
    primary = ranked_skips[0][0] if ranked_skips else None

    ab: list[dict[str, Any]] = []
    buf = float(crt_params.get("distribution_inside_buffer_frac", 0.0)) if isinstance(crt_params, dict) else 0.0
    preset = str(crt_params.get("_preset_label", crt_params.get("crt_preset", ""))) if isinstance(crt_params, dict) else ""

    if dist / n >= 0.30:
        ab.append(
            {
                "focus": "crt_no_distribution_inside",
                "rationale": f"{_pct(dist, n)}% of bars are distribution SKIPs under current C3-inside gate.",
                "next_experiment": (
                    "Re-run scripts/crt_signal_history.py with --crt-preset loose_plus "
                    "or --crt-distribution-buffer-frac 0.022 (then compare counts_by_reason vs this run)."
                ),
                "current_distribution_buffer_frac": buf,
                "current_preset_guess": preset or None,
            }
        )
    if manip / n >= 0.12:
        ab.append(
            {
                "focus": "crt_no_manipulation",
                "rationale": f"{_pct(manip, n)}% of bars lack a clean AMD+C3-inside path.",
                "next_experiment": (
                    "Try slightly higher distribution_inside_buffer_frac first; if still stuck, "
                    "accept lower signal rate or add a separate chop filter outside crt_signal_row."
                ),
            }
        )
    if tight > 0 and tight / n >= 0.001:
        ab.append(
            {
                "focus": "c1_range_too_tight",
                "rationale": f"{tight} bars ({_pct(tight, n)}%) veto tiny C1 ranges.",
                "next_experiment": "Lower --crt-min-range-pct further or use crt_preset loose / loose_plus defaults.",
            }
        )
    if conflict > 0:
        ab.append(
            {
                "focus": "crt_sweep_conflict",
                "rationale": f"{conflict} bars hit both-side sweep.",
                "next_experiment": "Already using prefer_* resolves conflict; compare prefer_bull vs prefer_bear on toy PnL.",
            }
        )

    dig: dict[str, Any] = {
        "dig_version": 1,
        "premise": (
            "UP/DOWN labels stay the two AMD templates in crt_signal_row; improvement is mostly "
            "converting SKIPs via distribution buffer, min range, presets, and optional session filters — "
            "not new reason strings."
        ),
        "bars": n,
        "skip_bars": skip_n,
        "direction_bars": up_n + down_n,
        "up_down_ratio": round(up_n / down_n, 4) if down_n else None,
        "skip_mix_pct_of_all_bars": skip_mix,
        "primary_skip_driver": primary,
        "skip_reason_rank": [{"reason": k, "count": v, "pct_of_bars": _pct(v, n)} for k, v in ranked_skips[:8]],
        "suggested_ab_runs": ab,
    }

    if not isinstance(enriched, dict):
        return dig

    after = enriched.get("after_skip_next_side_counts") or {}
    dist_next = after.get("crt_no_distribution_inside") if isinstance(after, dict) else None
    if isinstance(dist_next, dict) and dist_next:
        tot = sum(int(x) for x in dist_next.values())
        if tot > 0:
            dig["after_crt_no_distribution_inside_next_bar"] = {
                k: {"count": int(v), "pct": round(100.0 * int(v) / tot, 2)}
                for k, v in sorted(dist_next.items(), key=lambda x: -x[1])
            }

    hours_raw = enriched.get("signal_counts_by_hour_utc") or {}
    if isinstance(hours_raw, dict) and hours_raw:
        pairs = sorted(((int(h), int(c)) for h, c in hours_raw.items()), key=lambda x: -x[1])
        dig["top_signal_hours_utc"] = [{"hour_utc": h, "count": c} for h, c in pairs[:6]]

    mech = enriched.get("row_truth_rates_all_bars")
    if isinstance(mech, dict):
        dig["mechanical_row_rates"] = mech

    hby = enriched.get("htf_rp_c1_quantiles_by_reason") or {}
    if isinstance(hby, dict):
        def _p50(label: str) -> float | None:
            q = hby.get(label)
            if not isinstance(q, dict):
                return None
            v = q.get("p50")
            return float(v) if v is not None and math.isfinite(float(v)) else None

        p_dist = _p50("crt_no_distribution_inside")
        p_manip = _p50("crt_no_manipulation")
        p_up = _p50(KNOWN_UP_REASON)
        p_dn = _p50(KNOWN_DOWN_REASON)
        dig["htf_rp_c1_p50_by_reason"] = {
            "crt_no_distribution_inside": p_dist,
            "crt_no_manipulation": p_manip,
            KNOWN_UP_REASON: p_up,
            KNOWN_DOWN_REASON: p_dn,
        }
        if p_dist is not None and p_up is not None and p_dn is not None:
            mid_signals = 0.5 * (p_up + p_dn)
            dig["htf_narrative"] = (
                f"Distribution-SKIP bars median HTF_rp≈{p_dist:.3f} vs UP median≈{p_up:.3f} / DOWN≈{p_dn:.3f}; "
                f"mid of signal medians≈{mid_signals:.3f}. "
                "If SKIP mass sits between bull/bear signal bands, HTF re-enable (loose_htf) is a fair A/B."
            )

    return dig


def build_lessons_payload(
    *,
    meta: dict[str, Any],
    summary: dict[str, Any],
    enriched: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge run metadata + :func:`summarize_side_reason` into one JSON-serializable blob."""
    skip_sorted = summary.get("skip_reason_rarity_sorted") or []
    # skip_sorted is ascending by count: [:k] = rarest SKIPs, [-k:] = most common SKIPs.
    rarest_skips = skip_sorted[:5] if skip_sorted else []
    most_skips = skip_sorted[-5:] if skip_sorted else []

    hints: list[str] = []
    cr = summary.get("counts_by_reason") or {}
    cs = summary.get("counts_by_side") or {}
    if isinstance(cr, dict):
        dist = int(cr.get("crt_no_distribution_inside", 0))
        manip = int(cr.get("crt_no_manipulation", 0))
        n = int(summary.get("bars") or 1)
        if dist / n >= 0.25:
            hints.append(
                "crt_no_distribution_inside is material: try crt_preset loose_plus, "
                "or raise distribution_inside_buffer_frac slightly in backtest before live."
            )
        if manip / n >= 0.15:
            hints.append(
                "crt_no_manipulation is material: sweeps often absent or C3 not inside C1; "
                "loosen inside band or review strict AMD vs chop regimes."
            )
        tight = int(cr.get("c1_range_too_tight", 0))
        if tight > 0 and tight / n >= 0.002:
            hints.append(
                f"c1_range_too_tight appears {tight}x ({100.0 * tight / n:.2f}% of bars): "
                "try lower --crt-min-range-pct or looser preset so tiny C1 ranges are not vetoed."
            )
        conf = int(cr.get("crt_sweep_conflict", 0))
        if conf > 0:
            hints.append(
                f"crt_sweep_conflict count={conf}: use --crt-sweep-conflict prefer_bull|prefer_bear "
                "or accept skip when both sides swept."
            )
        warm = int(cr.get("warmup", 0)) + int(cr.get("warmup_vol", 0))
        if warm > 0:
            hints.append(
                f"warmup / warmup_vol rows={warm}: extend --warmup-days when backtesting from range_start, "
                "or ignore earliest bars in analysis."
            )
        vol = int(cr.get("crt_no_volume_confirm", 0))
        if vol > 0:
            hints.append(
                f"crt_no_volume_confirm={vol}: volume gate is on in params; default research runs usually keep it off."
            )
    if isinstance(cs, dict):
        up = int(cs.get("UP", 0))
        down = int(cs.get("DOWN", 0))
        sig = max(up + down, 1)
        if up > 1.35 * down:
            hints.append(
                f"UP-heavy sample (UP={up} vs DOWN={down}): check prefer_bull conflict resolution and bull sweep bias."
            )
        elif down > 1.35 * up:
            hints.append(
                f"DOWN-heavy sample (DOWN={down} vs UP={up}): check regime or conflict resolution asymmetry."
            )
    if most_skips:
        hints.append(
            "Most common SKIP reasons (tune these first): "
            f"{[x['reason'] for x in reversed(most_skips)]}"
        )
    if rarest_skips:
        hints.append(
            "Rarest SKIP reasons (sanity-check edge cases): "
            f"{[x['reason'] for x in rarest_skips if x.get('count', 0) > 0]}"
        )

    crt_params: dict[str, Any] | None = None
    if isinstance(meta, dict):
        crt_params = dict(meta.get("crt_params_effective") or {})
        if meta.get("crt_preset") is not None:
            crt_params["_preset_label"] = meta["crt_preset"]
    tuning_dig = derive_tuning_dig(summary, enriched, crt_params)

    out: dict[str, Any] = {
        "schema_version": 2 if enriched else 1,
        "meta": meta,
        "summary": summary,
        "improvement_hints": hints,
        "tuning_dig": tuning_dig,
    }
    if enriched:
        out["enriched"] = enriched
    return out


def params_to_jsonable(params: Any) -> dict[str, Any]:
    if is_dataclass(params):
        return {k: _jsonable(v) for k, v in asdict(params).items()}
    return {}


def _jsonable(x: Any) -> Any:
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return repr(x)
