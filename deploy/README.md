# VPS systemd (paper bots — no CLOB orders)

Copy units (adjust paths/user if needed), reload, enable:

```bash
sudo cp deploy/polymarket-crt-dryrun.service deploy/polymarket-crt-sweet-spot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now polymarket-crt-dryrun.service polymarket-crt-sweet-spot.service
```

Logs:

```bash
journalctl -u polymarket-crt-dryrun.service -f
journalctl -u polymarket-crt-sweet-spot.service -f
```

JSONL under repo `var/` (see `ExecStart` in each unit). Set `STRATEGY_EVAL_JOURNAL` in `.env` for a combined eval file.

Prereq: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt` from the repo root; `.env` readable by the service user.

Optional **CLOB** cron (not enabled by default): `scripts/clob_health.py --strict`, `scripts/clob_reconcile.py`, and one-off `scripts/clob_smoke.py` (see `.env.example` ``LIVE_*`` keys).
