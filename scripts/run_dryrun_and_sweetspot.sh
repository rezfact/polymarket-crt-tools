#!/usr/bin/env bash
# **Dryrun** (CRT, all assets, Pyth, bar-change log) + **sweet-spot** (BTC paper, Chainlink+fib).
# Thin wrapper around ``run_paper_session_2h.sh`` — same env vars.
#
# Fresh 2-hour session:
#   CLEAR_LOGS=1 ./scripts/run_dryrun_and_sweetspot.sh
#
# Run until Ctrl+C:
#   FOREVER=1 CLEAR_LOGS=1 ./scripts/run_dryrun_and_sweetspot.sh
#
# Optional ``repo/.env`` (not committed) with e.g.:
#   export POLYGON_RPC_URL="https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY"
#
# Other env: DURATION_SEC, CRT_NO_HTF, CRT_SWEEP, STICKY_ARM (default 1 for sweet-spot),
#   CRT_MIN_RANGE_PCT, INTERVAL_SEC, SWEET_INTERVAL, JOURNAL_DRY, JOURNAL_SWEET, STATE_DRY, LOG
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/run_paper_session_2h.sh"
