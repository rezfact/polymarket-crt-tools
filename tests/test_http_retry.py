from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests


def test_requests_get_response_retries_connection_error() -> None:
    from polymarket_htf.http_retry import requests_get_response

    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()

    with patch("polymarket_htf.http_retry.requests.get", side_effect=[requests.exceptions.ConnectionError("x"), ok]) as m:
        r = requests_get_response(
            "https://example.test/x",
            headers={"User-Agent": "t"},
            timeout=5.0,
            verify=True,
            attempts=4,
            base_sleep=0.01,
            max_sleep=0.05,
        )
    assert r is ok
    assert m.call_count == 2


def test_requests_get_response_raises_after_exhausted() -> None:
    from polymarket_htf.http_retry import requests_get_response

    with patch(
        "polymarket_htf.http_retry.requests.get",
        side_effect=requests.exceptions.ConnectionError("x"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            requests_get_response(
                "https://example.test/x",
                headers={"User-Agent": "t"},
                timeout=5.0,
                verify=True,
                attempts=2,
                base_sleep=0.01,
                max_sleep=0.05,
            )
