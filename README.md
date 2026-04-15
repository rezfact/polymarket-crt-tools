# polymarket_htf (btc15m workspace)

Python toolkit for **15m / 5m** Polymarket crypto Up/Down **slug discovery**, a **mechanical 3-candle CRT (AMD)** signal (Candle-1 CRH/CRL → Candle-2 liquidity sweep → Candle-3 close back inside, optional HTF zone filter), **backtest** on **Pyth Benchmarks TV** OHLC by default (optional Binance), **dry-run journaling**, and **EOA redeem** for resolved positions.

**Language:** Python matches the sibling `btc5m` repo (pandas backtests, same Gamma slug convention, `web3` redeem). Node is fine for HTTP bots, but you already have a full research stack in Python.

**CRT note:** Discretionary session timing, CHOCH/MSS on lower TFs, and 50% TP rules from full CRT are **not** encoded; extend the module if you add 1m data or session filters. Use ``--crt-no-htf-filter`` on the backtest CLI to relax the HTF location gate.

## Setup

```bash
cd /Users/rezza_fadillah/Work/me/poly/btc15m
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Commands

```bash
# Backtest (default: Pyth OHLC — not Chainlink settlement)
python scripts/backtest.py --asset btc --exec-interval 15m
# With sizing: USDC spent = max($1, floor(10% × capital)); PnL uses Polymarket-style **shares = USDC / entry** and $1/share redemption if you win. Optional separate NO mid for DOWN:
python scripts/backtest.py --asset btc --initial-capital 20 --yes-entry-mid 0.52 --no-entry-mid 0.50 --fee-roundtrip-bps 50
# Q1 2026 (UTC), Pyth history with warmup before Jan 1 (use ``--price-source binance`` only if you can reach Binance)
python scripts/backtest.py --asset btc --initial-capital 5 --start 2026-01-01 --end 2026-04-01

# Scan active Gamma slugs (needs network)
python scripts/scan_slugs.py --tf 15

# Dry-run loop: logs JSONL intents to var/journal.jsonl
python scripts/dryrun.py --tf 15 --once

# Sweet-spot paper watcher (use **.venv313** so you are not on macOS system Python 3.9; CRT defaults to **Pyth**)
./scripts/watch_sweet_spot_venv.sh --once
# If TLS to Binance still fails (corporate proxy), keep ``--price-source pyth`` (default) or set a custom CA:
#   export REQUESTS_CA_BUNDLE="$(python -c 'import certifi; print(certifi.where())')"

# Redeem resolved wins — dry-run first (needs POLYGON_PRIVATE_KEY + MATIC for execute)
python scripts/redeem_wins.py
python scripts/redeem_wins.py --crypto-only --journal var/redeem.jsonl
python scripts/redeem_wins.py --execute
```

## Environment

| Variable | Purpose |
|----------|---------|
| `POLYMARKET_PRIVATE_KEY` / `POLYGON_PRIVATE_KEY` | Redeem signing (EOA must hold tokens) |
| `POLYMARKET_FUNDER_ADDRESS` | If set, Data API queries this address (redeem still needs signer == holder for EOA path) |
| `POLYGON_RPC_URL` | Polygon HTTP RPC (optional **comma-separated** list, tried in order). If unset, Chainlink reads use built-in public fallbacks instead of only `polygon-rpc.com`. |
| `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` | If unset, importing HTTP helpers may set them from **certifi** (helps some macOS Python builds). |
| `REQUESTS_VERIFY` | Set to `0` / `false` to disable TLS verify (insecure; debugging only). |
| `POLYMARKET_GAMMA_EVENT_SLUG_URL` | Override Gamma base (default `…/events/slug`) |
| `HTTP_USER_AGENT` | Sent on Gamma (and Binance) requests; use a normal browser string on VPS if Gamma returns **403**. |
| `POLYMARKET_GAMMA_REFERER` | Referer header for Gamma (default `https://polymarket.com/`) |
| `POLYMARKET_GAMMA_AUTHORIZATION` | Optional `Authorization` value (e.g. `Bearer …`) if your tier requires it |
| `BINANCE_KLINES_URL` | Override REST origin if your network blocks `api.binance.com` (default `https://api.binance.com/api/v3/klines`) |

### Binance Vision (bulk files)

[Binance Data Collection](https://data.binance.vision/) hosts **monthly zip** archives. The path you linked
([`data/futures/um/monthly/klines/`](https://data.binance.vision/?prefix=data/futures/um/monthly/klines/))
is **USDT-M futures** — different from **spot** `BTCUSDT` used here.

For **spot** OHLCV (matches this repo’s symbols), Vision uses paths like
`data/spot/monthly/klines/BTCUSDT/15m/BTCUSDT-15m-YYYY-MM.zip`.

When REST klines are blocked, use **`--spot-vision`** (with `--start` / `--end`); zips are cached under `data/binance_vision/` by default:

```bash
python scripts/backtest.py --asset btc --initial-capital 5 --start 2026-01-01 --end 2026-04-01 --spot-vision
```

## Tests

```bash
pytest tests/ -q
```
