#!/usr/bin/env bash
# Paper sweet-spot watcher (Chainlink + fib 0.618-0.786 + pullback + Gamma).
# Use **same CRT loosening** as dryrun so arms match what dryrun would flag UP/DOWN.
#
# Foreground (Ctrl+C to stop):
#   ./scripts/run_sweet_spot_loose.sh
#
# Bounded run (e.g. alongside 2h dryrun):
#   DURATION_SEC=7200 CLEAR_LOGS=1 ./scripts/run_sweet_spot_loose.sh
#
# Optional env:
#   CRT_NO_HTF=1|0       default 1 (match run_dryrun_loose_2h.sh)
#   CRT_SWEEP=prefer_bull|prefer_bear|skip   default prefer_bull
#   CRT_MIN_RANGE_PCT    optional
#   PRICE_SOURCE=pyth|binance   default pyth (match dryrun)
#   INTERVAL_SEC=5
#   JOURNAL=var/watch_sweet_spot_loose.jsonl
#   CLEAR_LOGS=1         truncate journal before start
#   STICKY_ARM=1|0       default 1: keep arm if CRT flips next bar (--sticky-arm); 0 restores S3 revoke
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PY:-./.venv313/bin/python}"
INTERVAL_SEC="${INTERVAL_SEC:-5.0}"
JOURNAL="${JOURNAL:-var/watch_sweet_spot_loose.jsonl}"
PRICE_SOURCE="${PRICE_SOURCE:-pyth}"

CRT_NO_HTF="${CRT_NO_HTF:-1}"
CRT_SWEEP="${CRT_SWEEP:-prefer_bull}"
STICKY_ARM="${STICKY_ARM:-1}"

mkdir -p "$(dirname "$JOURNAL")"

if [[ "${CLEAR_LOGS:-0}" == "1" ]]; then
  rm -f "$JOURNAL"
  echo "cleared: $JOURNAL"
fi

CRT_ARGS=()
if [[ "${CRT_NO_HTF}" == "1" ]]; then CRT_ARGS+=(--crt-no-htf-filter); fi
if [[ -n "${CRT_SWEEP}" ]]; then CRT_ARGS+=(--crt-sweep-conflict "$CRT_SWEEP"); fi
if [[ -n "${CRT_MIN_RANGE_PCT:-}" ]]; then CRT_ARGS+=(--crt-min-range-pct "$CRT_MIN_RANGE_PCT"); fi
if [[ -n "${CRT_HTF_DISCOUNT_MAX:-}" ]]; then CRT_ARGS+=(--crt-htf-discount-max "$CRT_HTF_DISCOUNT_MAX"); fi
if [[ -n "${CRT_HTF_PREMIUM_MIN:-}" ]]; then CRT_ARGS+=(--crt-htf-premium-min "$CRT_HTF_PREMIUM_MIN"); fi
if [[ "${STICKY_ARM}" == "1" ]]; then CRT_ARGS+=(--sticky-arm); fi

run_watch() {
  exec "$PY" scripts/watch_sweet_spot.py \
    --asset btc \
    --tf 15 \
    --price-source "$PRICE_SOURCE" \
    --interval-sec "$INTERVAL_SEC" \
    --journal "$JOURNAL" \
    "${CRT_ARGS[@]}"
}

echo "repo=$ROOT journal=$JOURNAL price_source=$PRICE_SOURCE CRT_NO_HTF=${CRT_NO_HTF} CRT_SWEEP=${CRT_SWEEP} STICKY_ARM=${STICKY_ARM}"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ -n "${DURATION_SEC:-}" ]]; then
  echo "bounded run: ${DURATION_SEC}s (set DURATION_SEC empty for foreground-only)"
  run_watch &
  wid=$!
  cleanup() {
    if kill -0 "$wid" 2>/dev/null; then
      kill "$wid" 2>/dev/null || true
      wait "$wid" 2>/dev/null || true
    fi
    echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "--- tail sweet-spot journal ---"
    tail -n 25 "$JOURNAL" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM
  sleep "$DURATION_SEC"
  cleanup
  trap - EXIT INT TERM
else
  run_watch
fi
