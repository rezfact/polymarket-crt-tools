# Confidence runbook (paper data vs live test money)

Use this when you want **structured learning**: cheap live tickets, continuous **paper** logs for the next strategy iteration, and clear stop rules.

## Core split (important)

| Track | What runs it | Real money? | Purpose |
|--------|----------------|-------------|---------|
| **Paper** | `polymarket-crt-dryrun.service`, `polymarket-crt-sweet-spot.service` | **No** (JSONL only) | Signals, gates, `wss_diag`, proxy settlements — **keep these running** for data even if live testing stops. |
| **Live** | Polymarket UI and/or a future CLOB script (not the shipped sweet-spot unit) | **Yes** | Prove fills, fees, and PnL vs assumptions. |

**Stopping or pausing live trading must not stop the paper units.** Paper and live are independent; if live balance goes to **$0**, paper still accumulates `var/dryrun.jsonl` and `var/watch_sweet_spot.jsonl` on the VPS.

---

## Step 1 — Run paper and live in parallel

1. On the VPS, keep **`polymarket-crt-dryrun.service`** and **`polymarket-crt-sweet-spot.service`** enabled (see `deploy/README.md`).
2. For each window you care about, note **UTC time / slug** from paper JSONL (`paper_fill`, `wss_diag`, arms).
3. When you place a **live** trade (manual or script), log: time, market, side, size, price, and the **same** window slug if possible.
4. After settlement, tag **paper vs live**: same window, compare gate state from paper vs what you actually got filled at.
5. **Batch compare paper fills to books (no orders):** from repo root, with `.env` loaded (Gamma + optional CLOB keys),

   ```bash
   python scripts/examine_paper_fills_live.py --journal var/watch_sweet_spot.jsonl --last 8
   ```

   For each recent `paper_fill`, this fetches **Gamma** side mids vs your **toy** mid (default 0.5 YES) and, if CLOB keys are set, **bid / ask / spread** for the matching outcome token. It prints suggested **`clob_smoke.py`** lines for a **$1 dry-run** or **`--execute`** (still gated by `LIVE_TRADING_ENABLED` + kill-switch). Closed-window slugs may **404** on Gamma — that is normal.

**Goal:** See whether live disagrees with paper (price, timing, skips) before you trust backtest PnL.

---

## Step 2 — Short post-session checklist (data for the next improvement)

After each session (or daily), append to a note or spreadsheet:

- Paper: count of arms, `paper_fill` / timeout / skip reasons; any Gamma or HTTP errors in `journalctl`.
- Live: number of tickets, stake each, net PnL, ending **tradable balance**.
- One line: **“Did anything break our assumptions?”** (e.g. could not enter, price worse than 0.5 toy mid, missed window.)

Archive JSONL periodically so you can run `scripts/analyze_*` or ad-hoc Python later.

---

## Step 3 — Live-only stop rules (test bankroll)

These apply **only to real-money placement**, not to systemd paper services.

1. **Primary rule (your spec):** stop placing **live** bets when **tradable cash balance ≤ $1**.  
   - Rationale: this is dedicated test capital; preserve the last dollar and avoid grinding fees to zero; below ~$1, min-ticket sizing is awkward anyway.
2. **Optional add-ons** (tighten if you want): max **-$N** live PnL in a calendar day; stop after **N** consecutive live losses; time-box (“review after 2 weeks”).
3. **Never** use balance-based stops to `systemctl stop polymarket-crt-sweet-spot` — you want **paper data even when live is idle or at $0**.

**Goal:** Bounded downside on live; uninterrupted paper stream for research.

---

## Step 4 — Periodically re-check research with Gamma

Sims often use **`skip_gamma`**; live touches real books. On a schedule (e.g. weekly):

- Run `scripts/month_crt_wss.py` (or a short date range) with **Gamma on** / mids at fill if you have flags for that, and compare **ranking of presets** (e.g. `late_window_quality` vs `continuation`) vs your last `skip_gamma` sweep.

**Goal:** Preset choice still makes sense when entry prices are not a flat 0.5 toy.

---

## Step 5 — Forward paper only on “new” time

Keep paper running through weeks you have **not** heavily backtested. If paper behavior drifts (new regime, API errors), fix ops first, then reinterpret old sims.

**Goal:** Reduce overfitting to one historical slice.

---

## Step 6 — Add live capital only after evidence

Raise live size or bankroll only when:

- You have enough **paired** paper vs live rows to see stable patterns (not one lucky day).
- Live stop rules were never violated because of bugs (e.g. forgot to stop at ≤$1).
- You are comfortable that fees + spread + missed fills are priced into expectations.

**Goal:** Scale follows evidence, not backtest compounding curves alone.

---

## Implement on the VPS (automated check + on-disk rules)

This repo cannot SSH to your server for you. After **`ssh nevacloud`** (or your host alias), use the **repo checkout path on that host** (e.g. **`/opt/polymarket-crt-tools`** — this is what the shipped systemd units use; it is **not** `/opt/project` unless you symlink yourself).

```bash
cd /opt/polymarket-crt-tools   # match WorkingDirectory= in deploy/*.service
git pull origin main            # optional: get latest deploy scripts
chmod +x deploy/vps_confidence_check.sh
bash deploy/vps_confidence_check.sh
```

If **`git pull`** fails with **`.git/FETCH_HEAD: Permission denied`**, some objects under `.git` were probably created as **root** during an earlier `sudo git` operation. One-time fix (on the VPS): `sudo chown -R deploy:deploy /opt/polymarket-crt-tools/.git`, then `git pull` again as **`deploy`**.

**`.env` only (no secrets printed):** from the same repo root,

```bash
.venv/bin/python deploy/check_vps_env.py --repo-root "$(pwd)"
# fail CI / deploy gate on warnings:
.venv/bin/python deploy/check_vps_env.py --repo-root "$(pwd)" --strict
```

The script picks **`EnvironmentFiles=`** from `polymarket-crt-sweet-spot.service` when `--env-file` is omitted, else uses **`./.env`**. It checks the **paper-bot checklist** from `.env.example`: real **`HTTP_USER_AGENT`** (not the library default), optional Gamma/Pyth/journal keys, and flags **`REQUESTS_VERIFY=0`**.

The bundled script:

- Reports whether **`polymarket-crt-dryrun.service`** and **`polymarket-crt-sweet-spot.service`** are **active** (and hints `systemctl enable --now` if not).
- Summarises **`var/dryrun.jsonl`** / **`var/watch_sweet_spot.jsonl`** line counts.
- Writes **`var/LIVE_TEST_RULES.txt`** with your **≤ $1** live stop line and a reminder **not** to stop paper units for balance reasons.

Re-run after deploys or when debugging. Override repo root: `REPO_ROOT=/path/to/repo bash deploy/vps_confidence_check.sh`.

---

## Quick reference: commands (paper stays up)

```bash
# Paper (data) — leave running
sudo systemctl status polymarket-crt-dryrun.service polymarket-crt-sweet-spot.service
journalctl -u polymarket-crt-sweet-spot.service -n 50 --no-pager
```

**Live** stop is a **human rule** (or a future bot guard): do not place orders when balance ≤ $1; paper services unchanged.

---

## Optional: auto-CLOB from `paper_fill` (real money — high risk)

`scripts/live_follow_paper_fill.py` tails **`var/watch_sweet_spot.jsonl`**, and for each new **`paper_fill`** (deduped by `slug|T|side`) either logs a **plan** or posts **one** small GTC-style **BUY** on the matching outcome token when run with **`--execute`**.

**Guards:** `LIVE_TRADING_ENABLED=1`, no kill-switch file, optional **`LIVE_TRADING_MIN_COLLATERAL_USD`** (e.g. `1` → skip when CLOB collateral **≤** $1), notional cap **`LIVE_FOLLOW_PAPER_MAX_USD`** (default **$1**). If collateral cannot be read, orders are **still attempted** (CLOB may reject).

**State:** `var/live_follow_paper/journal_byte_offset.txt`, `processed_keys.txt`, `follow_audit.jsonl` (do not delete mid-run unless you accept re-trading old fills after resetting offset).

```bash
# Dry-run once (marks fills processed after logging plan — no CLOB submit)
python scripts/live_follow_paper_fill.py --journal var/watch_sweet_spot.jsonl --once

# Live (real BUYs) — only after `.env` is correct
LIVE_TRADING_ENABLED=1 python scripts/live_follow_paper_fill.py --journal var/watch_sweet_spot.jsonl --execute
```

A **plan-only** run still appends to **`processed_keys.txt`**. If you preview with `--once` then want **real** orders on the **same** `paper_fill` lines, delete or move **`var/live_follow_paper/`** (or use a fresh `--state-dir`) before `--execute`.

Example systemd unit (copy by hand, **not** installed by default): `deploy/polymarket-crt-live-follow.service.example`.

**Caveats:** no sell / TP wiring; same-window risk as manual; race if two followers run; collateral API shape may vary — tune `polymarket_htf/clob_collateral.py` if your client returns a different JSON.

**Telegram:** set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. With `--execute`, `live_follow_paper_fill` sends a **start** message and one message per important outcome (order posted, low collateral, kill-switch, missing book, etc.). Set `LIVE_FOLLOW_TELEGRAM=0` to turn off.

---

## Related docs

- `deploy/README.md` — install, restart, Gamma 403, paths.
- `.env.example` — Gamma + HTTP user agent for paper bots.
