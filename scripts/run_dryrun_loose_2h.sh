#!/usr/bin/env bash
# CRT dryrun for 2 hours with **looser** defaults (fewer SKIPs from HTF / sweep-conflict).
#
#   CLEAR_LOGS=1 ./scripts/run_dryrun_loose_2h.sh
#
# Optional env (override defaults):
#   DURATION_SEC=7200
#   CRT_PRESET=loose|loose_htf|default   (default here: loose)
#   CRT_NO_HTF=1         append --crt-no-htf-filter after preset (e.g. force off HTF with loose_htf)
#   CRT_SWEEP=prefer_bear   tie-break when both sides swept (wins over preset prefer_bull)
#   CRT_MIN_RANGE_PCT=0.0001   lower → fewer c1_range_too_tight SKIPs
#   CRT_HTF_DISCOUNT_MAX / CRT_HTF_PREMIUM_MIN  widen bull/bear HTF bands
#   INTERVAL_SEC=60
#   JOURNAL=var/dryrun_loose_2h.jsonl STATE=var/dryrun_loose_2h_state.json LOG=var/dryrun_loose_2h.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PY:-./.venv313/bin/python}"
DURATION_SEC="${DURATION_SEC:-7200}"
INTERVAL_SEC="${INTERVAL_SEC:-60}"
JOURNAL="${JOURNAL:-var/dryrun_loose_2h.jsonl}"
STATE="${STATE:-var/dryrun_loose_2h_state.json}"
LOG="${LOG:-var/dryrun_loose_2h.log}"

# Looser CRT: use --crt-preset loose (see polymarket_htf/crt_presets.py). Override:
#   CRT_PRESET=loose_htf|default
#   CRT_SWEEP=prefer_bear  → appended after preset so it wins
CRT_PRESET="${CRT_PRESET:-loose}"
CRT_SWEEP="${CRT_SWEEP:-}"

mkdir -p "$(dirname "$JOURNAL")" "$(dirname "$STATE")" "$(dirname "$LOG")"

if [[ "${CLEAR_LOGS:-0}" == "1" ]]; then
  rm -f "$JOURNAL" "$LOG" "$STATE"
  echo "cleared: $JOURNAL $LOG $STATE"
fi

echo "repo=$ROOT"
echo "duration=${DURATION_SEC}s interval=${INTERVAL_SEC}s CRT_PRESET=${CRT_PRESET} CRT_SWEEP=${CRT_SWEEP:-}"
echo "journal=$JOURNAL state=$STATE log=$LOG"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"

CRT_EXTRA=(--crt-preset "$CRT_PRESET")
if [[ -n "${CRT_SWEEP}" ]]; then CRT_EXTRA+=(--crt-sweep-conflict "$CRT_SWEEP"); fi
if [[ -n "${CRT_MIN_RANGE_PCT:-}" ]]; then CRT_EXTRA+=(--crt-min-range-pct "$CRT_MIN_RANGE_PCT"); fi
if [[ -n "${CRT_HTF_DISCOUNT_MAX:-}" ]]; then CRT_EXTRA+=(--crt-htf-discount-max "$CRT_HTF_DISCOUNT_MAX"); fi
if [[ -n "${CRT_HTF_PREMIUM_MIN:-}" ]]; then CRT_EXTRA+=(--crt-htf-premium-min "$CRT_HTF_PREMIUM_MIN"); fi
if [[ "${CRT_NO_HTF:-0}" == "1" ]]; then CRT_EXTRA+=(--crt-no-htf-filter); fi

"$PY" scripts/dryrun.py \
  --tf 15 \
  --price-source pyth \
  --log-on-bar-change \
  --state-file "$STATE" \
  --interval-sec "$INTERVAL_SEC" \
  --journal "$JOURNAL" \
  "${CRT_EXTRA[@]}" \
  >>"$LOG" 2>&1 &
pid=$!
echo "dryrun_pid=$pid" | tee -a "$LOG"

cleanup() {
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
}
trap cleanup EXIT INT TERM

sleep "$DURATION_SEC"
cleanup
trap - EXIT INT TERM

echo "--- tail log ---"
tail -n 40 "$LOG"
echo "--- journal lines ---"
wc -l "$JOURNAL" 2>/dev/null || true
echo "--- last journal rows ---"
tail -n 20 "$JOURNAL" 2>/dev/null || true
