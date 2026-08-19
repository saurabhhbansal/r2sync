"""Unit tests for AutoUpdater module."""

from unittest.mock import MagicMock, patch
from r2sync.core.updater import AutoUpdater, parse_version_tuple, UpdateInfo


def test_parse_version_tuple():
    assert parse_version_tuple("v1.1.1") == (1, 1, 1)
    assert parse_version_tuple("1.2.0") == (1, 2, 0)
    assert parse_version_tuple("v2.0") == (2, 0, 0)
    assert parse_version_tuple("3") == (3, 0, 0)


def test_check_for_updates_mock():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v9.9.9",
        "name": "Release 9.9.9",
        "body": "Major improvements",
        "html_url": "https://github.com/saurabhhbansal/r2sync/releases/tag/v9.9.9",
        "assets": [
            {
                "name": "r2sync-setup.exe",
                "browser_download_url": "https://github.com/saurabhhbansal/r2sync/releases/download/v9.9.9/r2sync-setup.exe",
                "size": 50000000,
            }
        ],
    }

    with patch("requests.get", return_value=mock_resp):
        info = AutoUpdater.check_for_updates()
        assert info.available is True
        assert info.latest_version == "9.9.9"
        assert "r2sync-setup.exe" in info.download_url
