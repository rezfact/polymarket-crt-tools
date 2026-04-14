from __future__ import annotations

import os
from pathlib import Path


def _requests_verify_disabled() -> bool:
    raw = os.getenv("REQUESTS_VERIFY")
    if raw is None or not str(raw).strip():
        return False
    return str(raw).strip().lower() in {"0", "false", "no", "off"}


def load_dotenv_files(*, project_root: Path | None = None) -> None:
    """
    Load ``.env`` into ``os.environ`` (does not override variables already set in the shell).

    Order: repository root ``.env`` (parent of ``polymarket_htf``), then current working directory.
    If ``python-dotenv`` is not installed, this is a no-op (VPS should ``pip install -r requirements.txt``).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = project_root if project_root is not None else Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env", override=False)
    load_dotenv(override=False)


def strategy_eval_journal_path() -> Path | None:
    """
    Optional **second** JSONL path for long-term strategy evaluation (paper + future live).

    Set ``STRATEGY_EVAL_JOURNAL`` (or alias ``LIVE_EVAL_JOURNAL``), e.g. on a VPS::

        STRATEGY_EVAL_JOURNAL=/var/log/polymarket_htf/strategy_eval.jsonl

    :func:`polymarket_htf.journal.append_jsonl_with_eval_mirror` writes the same row as the primary
    journal plus ``pipeline`` (``dryrun``, ``sweet_spot``, or later ``live``).
    """
    raw = os.getenv("STRATEGY_EVAL_JOURNAL") or os.getenv("LIVE_EVAL_JOURNAL")
    if not raw or not str(raw).strip():
        return None
    return Path(str(raw).strip()).expanduser()


def env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    s = raw.strip()
    return s if s else default


def env_optional_str(name: str) -> str | None:
    """Unset or blank → ``None``."""
    raw = os.getenv(name)
    if raw is None:
        return None
    s = raw.strip()
    return s if s else None


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return float(str(raw).strip())


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return int(str(raw).strip())


def http_user_agent() -> str:
    return env_str("HTTP_USER_AGENT", "Mozilla/5.0 (compatible; polymarket_htf/0.1; +local)")


def binance_klines_url() -> str:
    return env_str("BINANCE_KLINES_URL", "https://api.binance.com/api/v3/klines")


def gamma_event_slug_url() -> str:
    return env_str(
        "POLYMARKET_GAMMA_EVENT_SLUG_URL",
        "https://gamma-api.polymarket.com/events/slug",
    ).rstrip("/")


def polygon_rpc_url_candidates() -> list[str]:
    """
    Ordered Polygon HTTP JSON-RPC endpoints for read-only calls (Chainlink, etc.).

    - If ``POLYGON_RPC_URL`` is set: use it as a single URL, or **comma-separated**
      list (tried in order). Empty / unset → built-in public fallbacks (more stable
      than the old single default ``polygon-rpc.com``, which often 405s or resets).
    """
    raw = os.getenv("POLYGON_RPC_URL")
    if raw is not None:
        s = raw.strip()
        if s:
            return [p.strip() for p in s.split(",") if p.strip()]
    return [
        "https://polygon-bor-rpc.publicnode.com",
        "https://1rpc.io/matic",
        "https://rpc.ankr.com/polygon",
        "https://polygon-rpc.com",
    ]


def polygon_rpc_url() -> str:
    """First RPC URL (backward compatible for callers that expect a single string)."""
    urls = polygon_rpc_url_candidates()
    return urls[0] if urls else "https://polygon-bor-rpc.publicnode.com"


def polygon_chainlink_btc_usd_feed() -> str:
    """Polygon mainnet BTC/USD Chainlink data proxy (checksum optional for web3)."""
    return env_str(
        "POLYGON_BTC_USD_CHAINLINK_FEED",
        "0xc907E116054Ad103354f2D350FD2514433D57F6f",
    )


def requests_verify() -> bool | str:
    """
    Value for ``requests`` TLS verification.

    - Unset / blank → ``True`` (use :func:`tls_verify_requests` certifi bundle).
    - ``0`` / ``false`` / ``no`` / ``off`` → ``False`` (no cert verification; dev only).
    - ``1`` / ``true`` / ``yes`` / ``on`` → ``True`` (do **not** treat ``1`` as a CA file path).
    - Existing file path → use that bundle.
    """
    raw = os.getenv("REQUESTS_VERIFY")
    if raw is None or not str(raw).strip():
        return True
    s = str(raw).strip()
    sl = s.lower()
    if sl in {"0", "false", "no", "off"}:
        return False
    if sl in {"1", "true", "yes", "on"}:
        return True
    if os.path.isfile(s):
        return s
    return True


def ensure_certifi_ssl_env() -> None:
    """
    If neither ``SSL_CERT_FILE`` nor ``REQUESTS_CA_BUNDLE`` is set, point them at **certifi**.

    Fixes common macOS/Homebrew Python setups where the default trust store is incomplete
    (``SSLCertVerificationError: unable to get local issuer certificate`` on Binance, Gamma, etc.).
    Skipped when ``REQUESTS_VERIFY`` disables TLS verification.

    Also **drops** ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` when they point at a non-existent
    path (common broken ``.env``), so certifi can be applied.
    """
    if _requests_verify_disabled():
        return
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        p = os.getenv(key)
        if not p or not str(p).strip():
            continue
        path = str(p).strip()
        if not os.path.isfile(path):
            os.environ.pop(key, None)
    if os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE"):
        return
    try:
        import certifi

        bundle = certifi.where()
    except ImportError:
        return
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)


def tls_verify_requests() -> bool | str:
    """``verify=`` value for ``requests``: honor ``REQUESTS_VERIFY``, else prefer certifi CA bundle."""
    v = requests_verify()
    if v is not True:
        return v
    try:
        import certifi

        return certifi.where()
    except ImportError:
        return True


def pyth_benchmarks_tv_history_url() -> str:
    """Pyth Benchmarks TradingView ``history`` endpoint (query string appended)."""
    return env_str(
        "PYTH_BENCHMARKS_TV_HISTORY_URL",
        "https://benchmarks.pyth.network/v1/shims/tradingview/history",
    )


def pyth_benchmarks_request_headers() -> dict[str, str]:
    """
    HTTP headers for Pyth **Benchmarks TradingView** OHLC requests (``pyth_prices.tv_history_raw``).

    The public ``benchmarks.pyth.network`` shim usually needs **no** key. If you have a Pyth
    **API key** (Pro / enterprise / partner), set ``PYTH_API_KEY`` or ``PYTH_BENCHMARKS_API_KEY``;
    it is sent as ``Authorization: <scheme> <key>`` (default scheme ``Bearer``). Override scheme
    with ``PYTH_API_AUTH_SCHEME`` (e.g. ``Bearer``, ``Token``). If the key must go in another
    header, set ``PYTH_API_KEY_HEADER`` to the header name (value = key; ``Authorization`` is not set).
    """
    h: dict[str, str] = {"User-Agent": http_user_agent()}
    key = env_optional_str("PYTH_API_KEY") or env_optional_str("PYTH_BENCHMARKS_API_KEY")
    if not key:
        return h
    custom_header = env_optional_str("PYTH_API_KEY_HEADER")
    if custom_header:
        h[custom_header.strip()] = key
        return h
    scheme = env_str("PYTH_API_AUTH_SCHEME", "Bearer").strip()
    if scheme.lower() in {"", "none", "raw"}:
        h["Authorization"] = key
    else:
        h["Authorization"] = f"{scheme} {key}"
    return h


def pyth_hermes_api_base() -> str:
    """Hermes REST base (no trailing path); e.g. ``https://hermes.pyth.network``."""
    return env_str("PYTH_HERMES_URL", "https://hermes.pyth.network").rstrip("/")


def poly_clob_host() -> str:
    """Polymarket CLOB HTTP API base (no trailing slash)."""
    return env_str("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com").rstrip("/")


def live_trading_enabled() -> bool:
    """Master switch: ``scripts/clob_smoke.py --execute`` requires this plus no kill-switch file."""
    return env_bool("LIVE_TRADING_ENABLED", False)


def live_smoke_max_usd() -> float:
    """Cap notional (price × size) for ``clob_smoke`` BUY (default ``3``)."""
    return env_float("LIVE_SMOKE_MAX_USD", 3.0)


def live_max_stake_usd() -> float | None:
    """Optional max USDC per slice for a future live worker (unset = no env cap)."""
    raw = env_optional_str("LIVE_MAX_STAKE_USD")
    if raw is None:
        return None
    return float(raw)


def live_kill_switch_path() -> Path | None:
    """
    If this path **exists** as a file, live order placement is treated as **paused**
    (``clob_smoke --execute`` exits; use ``touch`` / ``rm`` for a crude runbook).
    """
    raw = env_optional_str("LIVE_KILL_SWITCH_PATH")
    return Path(raw).expanduser() if raw else None


def live_trading_paused_by_file() -> bool:
    p = live_kill_switch_path()
    return bool(p and p.is_file())
