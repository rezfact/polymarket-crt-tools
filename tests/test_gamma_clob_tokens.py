from __future__ import annotations

from polymarket_htf.gamma import gamma_clob_token_ids_up_down


def test_gamma_clob_token_ids_parses_json_string() -> None:
    ev = {
        "markets": [
            {
                "clobTokenIds": '["111", "222"]',
            }
        ]
    }
    assert gamma_clob_token_ids_up_down(ev) == ("111", "222")


def test_gamma_clob_token_ids_parses_list() -> None:
    ev = {"markets": [{"clobTokenIds": ["aa", "bb"]}]}
    assert gamma_clob_token_ids_up_down(ev) == ("aa", "bb")


def test_gamma_clob_token_ids_missing() -> None:
    assert gamma_clob_token_ids_up_down({}) is None
