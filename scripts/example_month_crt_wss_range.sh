#!/usr/bin/env bash
# Example: CRT month batch + toy WR/PnL table over a custom UTC range.
# Usage:
#   ./scripts/example_month_crt_wss_range.sh
#   START=2026-01-10 END=2026-01-12 ./scripts/example_month_crt_wss_range.sh
#   CRT_PRESET=loose SKIP_WSS=1 ./scripts/example_month_crt_wss_range.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PY:-$ROOT/.venv313/bin/python}"
START="${START:-2026-01-01}"
END="${END:-2026-01-08}" # exclusive: 7 days of bars when START=01-01
ASSET="${ASSET:-btc}"
CRT_PRESET="${CRT_PRESET:-default}"
PRICE_SOURCE="${PRICE_SOURCE:-pyth}" # binance is faster when reachable
SKIP_WSS="${SKIP_WSS:-0}"
WSS_SPOT="${WSS_SPOT:-crt_15m}" # binance_1m when Binance works

CRT_OUT="var/example_crt_bars_${START}_${END}.jsonl"
WSS_OUT="var/example_wss_sim_${START}_${END}.jsonl"

args=(
  "$PY" scripts/month_crt_wss.py
  --asset "$ASSET"
  --start "$START"
  --end "$END"
  --price-source "$PRICE_SOURCE"
  --crt-preset "$CRT_PRESET"
  --crt-bars-out "$CRT_OUT"
  --toy-stake-usd 10
  --toy-yes-mid 0.5
)

if [[ "$SKIP_WSS" == "1" ]]; then
  args+=(--skip-wss)
else
  args+=(--wss-spot-source "$WSS_SPOT" --wss-out "$WSS_OUT")
fi

echo "Running: ${args[*]}"
exec "${args[@]}"
