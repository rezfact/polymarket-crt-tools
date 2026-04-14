#!/usr/bin/env bash
# Run CRT dryrun for DURATION_SEC (default 3600) with Pyth OHLC, bar-change-only logging.
# After it exits: read var/dryrun_1h.log (stdout) and var/dryrun_1h_session.jsonl (JSONL records).
#
# Fresh run (delete previous journal, log, and bar state):
#   CLEAR_LOGS=1 ./scripts/run_dryrun_1h.sh
#
# Looser CRT (fewer SKIPs from HTF / sweep-conflict tie-break):
#   CRT_NO_HTF=1 CRT_SWEEP=prefer_bull CLEAR_LOGS=1 ./scripts/run_dryrun_1h.sh
#
# (This repo also has a second “strategy” / process: sweet-spot paper watcher → scripts/watch_sweet_spot.py)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PY:-./.venv313/bin/python}"
DURATION_SEC="${DURATION_SEC:-3600}"
INTERVAL_SEC="${INTERVAL_SEC:-60}"
JOURNAL="${JOURNAL:-var/dryrun_1h_session.jsonl}"
STATE="${STATE:-var/dryrun_bar_state.json}"
LOG="${LOG:-var/dryrun_1h.log}"

mkdir -p "$(dirname "$JOURNAL")" "$(dirname "$STATE")" "$(dirname "$LOG")"

if [[ "${CLEAR_LOGS:-0}" == "1" ]]; then
  rm -f "$JOURNAL" "$LOG" "$STATE"
  echo "cleared: $JOURNAL $LOG $STATE"
fi

echo "repo=$ROOT"
echo "duration=${DURATION_SEC}s interval=${INTERVAL_SEC}s"
echo "journal=$JOURNAL state=$STATE log=$LOG"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"

CRT_EXTRA=()
if [[ "${CRT_NO_HTF:-0}" == "1" ]]; then CRT_EXTRA+=(--crt-no-htf-filter); fi
if [[ -n "${CRT_SWEEP:-}" ]]; then CRT_EXTRA+=(--crt-sweep-conflict "$CRT_SWEEP"); fi
if [[ -n "${CRT_MIN_RANGE_PCT:-}" ]]; then CRT_EXTRA+=(--crt-min-range-pct "$CRT_MIN_RANGE_PCT"); fi
if [[ -n "${CRT_HTF_DISCOUNT_MAX:-}" ]]; then CRT_EXTRA+=(--crt-htf-discount-max "$CRT_HTF_DISCOUNT_MAX"); fi
if [[ -n "${CRT_HTF_PREMIUM_MIN:-}" ]]; then CRT_EXTRA+=(--crt-htf-premium-min "$CRT_HTF_PREMIUM_MIN"); fi

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
tail -n 30 "$LOG"
echo "--- journal lines ---"
wc -l "$JOURNAL" 2>/dev/null || true
echo "--- last journal rows ---"
tail -n 15 "$JOURNAL" 2>/dev/null || true
