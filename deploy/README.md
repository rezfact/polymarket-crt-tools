# VPS systemd (paper bots — no CLOB orders)

## Paper strategy bundle (what the shipped units run)

| Unit | Role | Strategy knobs (in `ExecStart`) |
|------|------|----------------------------------|
| `polymarket-crt-dryrun.service` | Live **CRT** log (`var/dryrun.jsonl`) | `--tf 15` `--price-source pyth` `--crt-preset loose` HTF off + sweep `prefer_bull`, bar-change logging |
| `polymarket-crt-sweet-spot.service` | Live **WSS paper** (`var/watch_sweet_spot.jsonl`) | Same CRT bundle + **`--sticky-arm`** + **`--wss-preset continuation`** + **`--diag-interval-sec 45`** (`wss_diag` rows), Chainlink + fib + pullback |

Edit **`User=`**, **`Group=`**, and **`WorkingDirectory=`** in each unit if your checkout is not `/opt/polymarket-crt-tools` or user is not `deploy`.

**`.env`** on the VPS (loaded via `EnvironmentFile=-…/.env`): set at least a normal browser **`HTTP_USER_AGENT`** (and optional **`POLYMARKET_GAMMA_REFERER`**) so Gamma slug reads avoid **403**; see repo `.env.example` (Gamma + paper bots checklist). Optional **`STRATEGY_EVAL_JOURNAL`** for one combined JSONL with `pipeline` tags.

## Install

From repo root on a machine that has `sudo`:

```bash
chmod +x deploy/install_systemd_units.sh
./deploy/install_systemd_units.sh
sudo systemctl enable --now polymarket-crt-dryrun.service polymarket-crt-sweet-spot.service
```

Or copy by hand (adjust paths/user if needed), reload, enable:

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

Sweet-spot unit: `wss_diag` lines (when `--diag-interval-sec` is set) explain gates during each live window (entry window, pullback, fib distance, Gamma deviation). Match local month sims with `scripts/month_crt_wss.py --wss-preset continuation`.

Units load **`EnvironmentFile=-/opt/polymarket-crt-tools/.env`** so Gamma tuning applies without editing the unit. After copying updated units: `sudo systemctl daemon-reload && sudo systemctl restart polymarket-crt-dryrun.service polymarket-crt-sweet-spot.service`.

### Gamma `403 Forbidden` on `gamma-api.polymarket.com`

1. **Deploy latest code** (Gamma requests now send `Accept` + `Referer: https://polymarket.com/` by default).
2. On the VPS, in `/opt/polymarket-crt-tools/.env` (readable by `deploy`), set a **normal browser** `HTTP_USER_AGENT` (see `.env.example` near `POLYMARKET_GAMMA_EVENT_SLUG_URL`).
3. If Polymarket documents an API key for Gamma, set **`POLYMARKET_GAMMA_AUTHORIZATION`** (e.g. `Bearer …`).
4. If still blocked, change egress IP (VPN / another VPS) — some ranges are WAF-blocked.

Prereq: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt` from the repo root; `.env` readable by the service user.

**Verify:** `systemctl is-active polymarket-crt-dryrun.service polymarket-crt-sweet-spot.service` and `tail -f` the JSONL paths under `WorkingDirectory/var/`. After git pull, run `daemon-reload` and **restart** both units so `ExecStart` (e.g. WSS preset / diag) matches the new code.

Optional **CLOB** cron (not enabled by default): `scripts/clob_health.py --strict`, `scripts/clob_reconcile.py`, and one-off `scripts/clob_smoke.py` (see `.env.example` ``LIVE_*`` keys).
