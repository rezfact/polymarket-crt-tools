#!/usr/bin/env bash
# Run on the VPS from repo root (e.g. /opt/polymarket-crt-tools) after ssh.
# Verifies paper systemd units, touches JSONL paths, writes var/LIVE_TEST_RULES.txt.
set -euo pipefail

ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

UNITS=(polymarket-crt-dryrun.service polymarket-crt-sweet-spot.service)

echo "=== Confidence setup check (repo: $ROOT) ==="
echo

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  ENV_PY="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv313/bin/python" ]]; then
  ENV_PY="$ROOT/.venv313/bin/python"
else
  ENV_PY="python3"
fi
echo "=== .env requirements (no secrets printed; path from unit or $ROOT/.env) ==="
"$ENV_PY" "$ROOT/deploy/check_vps_env.py" --repo-root "$ROOT"
echo

for u in "${UNITS[@]}"; do
  if systemctl cat "$u" &>/dev/null; then
    state=$(systemctl is-active "$u" 2>/dev/null || true)
    if [[ "$state" == "active" ]]; then
      echo "[ok] $u is active"
    else
      echo "[warn] $u is NOT active (state=$state) — paper data may be stale. Try:"
      echo "       sudo systemctl enable --now $u"
    fi
  else
    echo "[warn] $u not installed — see deploy/README.md and deploy/install_systemd_units.sh"
  fi
done

echo
echo "=== Paper JSONL (paths under WorkingDirectory) ==="
mkdir -p "$ROOT/var"
for f in dryrun.jsonl watch_sweet_spot.jsonl; do
  p="$ROOT/var/$f"
  if [[ -f "$p" ]]; then
    lines=$(wc -l <"$p" | tr -d ' ')
    echo "[ok] var/$f  lines=$lines"
  else
    echo "[info] var/$f missing yet (normal before first events)"
  fi
done

RULES="$ROOT/var/LIVE_TEST_RULES.txt"
cat >"$RULES" <<'TXT'
# Live test money — human / future-bot rules (paper bots ignore this file)
# Written by deploy/vps_confidence_check.sh — safe to re-run.

LIVE_STOP_PLACE_BETS_WHEN_TRADABLE_USD_LTE=1

Meaning: stop placing real Polymarket orders when your tradable balance is <= $1.
Do NOT stop polymarket-crt-dryrun.service or polymarket-crt-sweet-spot.service for this;
paper JSONL keeps running for research when live is idle or at $0.

Optional: max daily live loss, max consecutive losses, calendar review — see deploy/CONFIDENCE_RUNBOOK.md
TXT
echo
echo "[ok] wrote $RULES"
echo
cat "$RULES"
echo
echo "=== Done. Re-run anytime:  REPO_ROOT=$ROOT bash deploy/vps_confidence_check.sh ==="
