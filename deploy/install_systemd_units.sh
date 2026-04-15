#!/usr/bin/env bash
# Copy paper-bot systemd units into /etc/systemd/system/ (paths in *.service default to
# /opt/polymarket-crt-tools and user deploy — edit those files first if your layout differs).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sudo install -m 0644 "$ROOT/deploy/polymarket-crt-dryrun.service" /etc/systemd/system/
sudo install -m 0644 "$ROOT/deploy/polymarket-crt-sweet-spot.service" /etc/systemd/system/
sudo systemctl daemon-reload
echo "Installed units. Next:"
echo "  sudo systemctl enable --now polymarket-crt-dryrun.service polymarket-crt-sweet-spot.service"
echo "  journalctl -u polymarket-crt-dryrun.service -f"
echo "  journalctl -u polymarket-crt-sweet-spot.service -f"
