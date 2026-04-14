from unittest.mock import MagicMock, patch

from polymarket_htf.positions_api import polymarket_positions_api_ping


def test_polymarket_positions_api_ping_ok():
    mock_r = MagicMock()
    mock_r.status_code = 200
    mock_r.json.return_value = [{"size": 1}]
    with patch("requests.get", return_value=mock_r):
        ok, detail = polymarket_positions_api_ping("0x0000000000000000000000000000000000000001")
    assert ok is True
    assert "rows_in_page=1" in detail


def test_polymarket_positions_api_ping_bad_json():
    mock_r = MagicMock()
    mock_r.status_code = 200
    mock_r.json.return_value = {}
    with patch("requests.get", return_value=mock_r):
        ok, detail = polymarket_positions_api_ping("0x0000000000000000000000000000000000000001")
    assert ok is False
