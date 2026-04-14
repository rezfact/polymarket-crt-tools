#!/usr/bin/env bash
# Run **both** loose CRT dryrun and sweet-spot watcher (paper only).
#
#   CLEAR_LOGS=1 ./scripts/run_paper_session_2h.sh
#
# Until Ctrl+C (no time limit):
#   FOREVER=1 CLEAR_LOGS=1 ./scripts/run_paper_session_2h.sh
#
# Optional: load secrets from repo-root ``.env`` (export lines only; do not commit):
#   set -a && [[ -f .env ]] && . ./.env && set +a
#
# Env: ``POLYGON_RPC_URL`` (Alchemy etc.), ``DURATION_SEC`` (default 7200), ``CRT_NO_HTF``, ``CRT_SWEEP``, …
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export DURATION_SEC="${DURATION_SEC:-7200}"
export CLEAR_LOGS="${CLEAR_LOGS:-0}"
export FOREVER="${FOREVER:-0}"
STICKY_ARM="${STICKY_ARM:-1}"

# Dedicated journals so the two processes do not share one file handle badly
export JOURNAL="${JOURNAL_DRY:-var/dryrun_loose_2h.jsonl}"
export STATE="${STATE_DRY:-var/dryrun_loose_2h_state.json}"
export LOG="${LOG:-var/dryrun_loose_2h.log}"

SWEET_JOURNAL="${JOURNAL_SWEET:-var/watch_sweet_spot_loose_2h.jsonl}"

if [[ "${CLEAR_LOGS}" == "1" ]]; then
  rm -f "$JOURNAL" "$LOG" "$STATE" "$SWEET_JOURNAL"
  echo "cleared dryrun: $JOURNAL $LOG $STATE"
  echo "cleared sweet: $SWEET_JOURNAL"
fi

if [[ "${FOREVER}" == "1" ]]; then
  echo "=== paper session FOREVER (Ctrl+C to stop) ==="
else
  echo "=== paper session ${DURATION_SEC}s ==="
fi
echo "dryrun journal=$JOURNAL"
echo "sweet-spot journal=$SWEET_JOURNAL"
echo "POLYGON_RPC_URL=${POLYGON_RPC_URL:+configured (value hidden)}${POLYGON_RPC_URL:-not set - built-in RPC fallbacks}"
echo "STICKY_ARM=${STICKY_ARM} (sweet-spot: 1=ignore CRT flip until fill/timeout)"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Start dryrun in background (inline; same flags as run_dryrun_loose_2h.sh)
PY="${PY:-./.venv313/bin/python}"
INTERVAL_SEC="${INTERVAL_SEC:-60}"
CRT_NO_HTF="${CRT_NO_HTF:-1}"
CRT_SWEEP="${CRT_SWEEP:-prefer_bull}"

mkdir -p "$(dirname "$JOURNAL")" "$(dirname "$STATE")" "$(dirname "$LOG")" "$(dirname "$SWEET_JOURNAL")"

CRT_EXTRA=()
if [[ "${CRT_NO_HTF}" == "1" ]]; then CRT_EXTRA+=(--crt-no-htf-filter); fi
if [[ -n "${CRT_SWEEP}" ]]; then CRT_EXTRA+=(--crt-sweep-conflict "$CRT_SWEEP"); fi
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
dry_pid=$!
echo "dryrun_pid=$dry_pid"

PRICE_SOURCE="${PRICE_SOURCE:-pyth}"
SWEET_INTERVAL="${SWEET_INTERVAL:-5.0}"
CRT_ARGS=()
if [[ "${CRT_NO_HTF}" == "1" ]]; then CRT_ARGS+=(--crt-no-htf-filter); fi
if [[ -n "${CRT_SWEEP}" ]]; then CRT_ARGS+=(--crt-sweep-conflict "$CRT_SWEEP"); fi
if [[ -n "${CRT_MIN_RANGE_PCT:-}" ]]; then CRT_ARGS+=(--crt-min-range-pct "$CRT_MIN_RANGE_PCT"); fi
if [[ -n "${CRT_HTF_DISCOUNT_MAX:-}" ]]; then CRT_ARGS+=(--crt-htf-discount-max "$CRT_HTF_DISCOUNT_MAX"); fi
if [[ -n "${CRT_HTF_PREMIUM_MIN:-}" ]]; then CRT_ARGS+=(--crt-htf-premium-min "$CRT_HTF_PREMIUM_MIN"); fi
if [[ "${STICKY_ARM}" == "1" ]]; then CRT_ARGS+=(--sticky-arm); fi

"$PY" scripts/watch_sweet_spot.py \
  --asset btc \
  --tf 15 \
  --price-source "$PRICE_SOURCE" \
  --interval-sec "$SWEET_INTERVAL" \
  --journal "$SWEET_JOURNAL" \
  "${CRT_ARGS[@]}" \
  >>"${LOG%.log}_sweet_spot.log" 2>&1 &
sweet_pid=$!
echo "sweet_spot_pid=$sweet_pid log_append=${LOG%.log}_sweet_spot.log"

cleanup() {
  for p in "$dry_pid" "$sweet_pid"; do
    if kill -0 "$p" 2>/dev/null; then
      kill "$p" 2>/dev/null || true
    fi
  done
  wait "$dry_pid" 2>/dev/null || true
  wait "$sweet_pid" 2>/dev/null || true
  echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
trap cleanup EXIT INT TERM

if [[ "${FOREVER}" == "1" ]]; then
  wait "$dry_pid" "$sweet_pid" 2>/dev/null || true
else
  sleep "$DURATION_SEC"
fi
cleanup
trap - EXIT INT TERM

echo "--- dryrun log (tail) ---"
tail -n 25 "$LOG"
echo "--- sweet-spot log (tail) ---"
tail -n 25 "${LOG%.log}_sweet_spot.log" 2>/dev/null || true
echo "--- dryrun journal lines ---"
wc -l "$JOURNAL" 2>/dev/null || true
echo "--- sweet-spot journal lines ---"
wc -l "$SWEET_JOURNAL" 2>/dev/null || true
echo "--- last sweet-spot events ---"
tail -n 15 "$SWEET_JOURNAL" 2>/dev/null || true
