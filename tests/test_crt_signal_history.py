from __future__ import annotations

from polymarket_htf.crt_signal_history import (
    KNOWN_DOWN_REASON,
    KNOWN_UP_REASON,
    build_lessons_payload,
    derive_tuning_dig,
    enrich_with_bar_context,
    summarize_side_reason,
)


def test_summarize_side_reason_counts_and_canonical_directions() -> None:
    sides = ["SKIP", "UP", "DOWN", "SKIP", "SKIP"]
    reasons = [
        "crt_no_manipulation",
        KNOWN_UP_REASON,
        KNOWN_DOWN_REASON,
        "crt_no_distribution_inside",
        "warmup",
    ]
    s = summarize_side_reason(sides, reasons)
    assert s["bars"] == 5
    assert s["counts_by_side"]["UP"] == 1
    assert s["counts_by_side"]["DOWN"] == 1
    assert s["counts_by_side"]["SKIP"] == 3
    assert s["direction_reasons_observed"]["anomaly_if_noncanonical"]["UP"] == []
    assert s["direction_reasons_observed"]["anomaly_if_noncanonical"]["DOWN"] == []


def test_summarize_detects_noncanonical_direction_reason() -> None:
    sides = ["UP", "DOWN"]
    reasons = ["weird_up", KNOWN_DOWN_REASON]
    s = summarize_side_reason(sides, reasons)
    assert s["direction_reasons_observed"]["anomaly_if_noncanonical"]["UP"] == ["weird_up"]


def test_enrich_with_bar_context_transitions() -> None:
    sides = ["SKIP", "SKIP", "UP", "DOWN"]
    reasons = ["crt_no_manipulation", "crt_no_distribution_inside", KNOWN_UP_REASON, KNOWN_DOWN_REASON]
    idx = ["2026-01-01T10:00:00+00:00", "2026-01-01T10:15:00+00:00", "2026-01-01T10:30:00+00:00", "2026-01-01T10:45:00+00:00"]
    htf = [0.2, 0.5, 0.3, 0.9]
    e = enrich_with_bar_context(
        sides=sides,
        reasons=reasons,
        index=idx,
        htf_rp_c1=htf,
        c1_range_pct=[0.01, 0.02, 0.015, 0.012],
    )
    assert "prev_reason_to_next_side_top" in e
    assert "after_skip_next_side_counts" in e
    assert e["after_skip_next_side_counts"]["crt_no_manipulation"]["SKIP"] == 1


def test_derive_tuning_dig_suggested_ab() -> None:
    summary = {
        "bars": 1000,
        "counts_by_side": {"SKIP": 700, "UP": 180, "DOWN": 120},
        "counts_by_reason": {
            "crt_no_distribution_inside": 500,
            "crt_no_manipulation": 200,
            KNOWN_UP_REASON: 180,
            KNOWN_DOWN_REASON: 120,
        },
    }
    enriched = {
        "after_skip_next_side_counts": {
            "crt_no_distribution_inside": {"SKIP": 300, "UP": 100, "DOWN": 80},
        },
        "signal_counts_by_hour_utc": {"10": 50, "11": 10},
        "row_truth_rates_all_bars": {"c3_inside_c1": 0.4},
    }
    d = derive_tuning_dig(summary, enriched, {"distribution_inside_buffer_frac": 0.015, "_preset_label": "loose"})
    assert d["dig_version"] == 1
    assert d["primary_skip_driver"] == "crt_no_distribution_inside"
    assert any(x["focus"] == "crt_no_distribution_inside" for x in d["suggested_ab_runs"])
    assert "after_crt_no_distribution_inside_next_bar" in d


def test_build_lessons_payload_has_hints() -> None:
    sides = ["SKIP"] * 100 + ["UP"] * 5
    reasons = ["crt_no_distribution_inside"] * 80 + ["crt_no_manipulation"] * 20 + [KNOWN_UP_REASON] * 5
    summary = summarize_side_reason(sides, reasons)
    out = build_lessons_payload(meta={"k": 1}, summary=summary)
    assert out["schema_version"] == 1
    assert "tuning_dig" in out
    assert "enriched" not in out
    assert "improvement_hints" in out
    assert any("crt_no_distribution_inside" in h for h in out["improvement_hints"])

    out2 = build_lessons_payload(meta={"k": 1}, summary=summary, enriched={"x": 1})
    assert out2["schema_version"] == 2
    assert out2["enriched"] == {"x": 1}
