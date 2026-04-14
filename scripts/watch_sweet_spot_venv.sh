#!/usr/bin/env bash
# Run sweet-spot with repo venv Python (avoids macOS ``env python3`` → Apple 3.9).
# Override: PY=/path/to/python ./scripts/watch_sweet_spot_venv.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "${PY:-}" ]]; then
  exec "$PY" "$ROOT/scripts/watch_sweet_spot.py" "$@"
fi
for cand in "$ROOT/.venv313/bin/python" "$ROOT/.venv/bin/python"; do
  if [[ -x "$cand" ]]; then
    exec "$cand" "$ROOT/scripts/watch_sweet_spot.py" "$@"
  fi
done
echo "error: no .venv313 or .venv; set PY=... or create a venv" >&2
exit 1
