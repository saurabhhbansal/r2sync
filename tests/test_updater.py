"""Unit tests for AutoUpdater module."""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from r2sync.core.updater import (
    AutoUpdater,
    IntegrityError,
    parse_version_tuple,
    UpdateInfo,
)


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


def _fake_stream(payload: bytes, content_length=None, chunk=8):
    """Build a requests.get replacement that streams payload in chunks."""
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.raise_for_status.return_value = None
    length = len(payload) if content_length is None else content_length
    resp.headers = {"content-length": str(length)}
    resp.iter_content.return_value = [payload[i:i + chunk] for i in range(0, len(payload), chunk)]
    return resp


def _info_for(payload: bytes, digest, size=None):
    return UpdateInfo(
        available=True,
        current_version="1.2.1",
        latest_version="1.2.2",
        release_name="Release v1.2.2",
        release_notes="notes",
        download_url="https://example.invalid/r2sync-setup.exe",
        asset_name="r2sync-setup.exe",
        asset_size=len(payload) if size is None else size,
        asset_digest=digest,
    )


def test_check_for_updates_captures_asset_digest():
    """The publisher-declared digest must survive the API parse."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v9.9.9",
        "name": "Release 9.9.9",
        "body": "notes",
        "assets": [{
            "name": "r2sync-setup.exe",
            "browser_download_url": "https://example.invalid/r2sync-setup.exe",
            "size": 1234,
            "digest": "sha256:" + "ab" * 32,
        }],
    }
    with patch("requests.get", return_value=mock_resp):
        info = AutoUpdater.check_for_updates()
    assert info.asset_digest == "sha256:" + "ab" * 32


def test_check_for_updates_tolerates_missing_digest():
    """Older releases predate the digest field; that must not break the check."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v9.9.9", "name": "n", "body": "b",
        "assets": [{"name": "r2sync-setup.exe",
                    "browser_download_url": "https://example.invalid/x.exe", "size": 10}],
    }
    with patch("requests.get", return_value=mock_resp):
        info = AutoUpdater.check_for_updates()
    assert info.available is True
    assert info.asset_digest is None


def test_download_verifies_digest_and_publishes_atomically(tmp_path):
    payload = b"MZ" + b"installer-bytes" * 40
    info = _info_for(payload, "sha256:" + hashlib.sha256(payload).hexdigest())
    out = tmp_path / "r2sync-setup.exe"

    seen = []
    with patch("requests.get", return_value=_fake_stream(payload)):
        path = AutoUpdater.download_update(info, progress_cb=lambda d, t: seen.append(d),
                                           target_path=out)

    assert path == out
    assert out.read_bytes() == payload
    assert not (tmp_path / "r2sync-setup.exe.part").exists(), "temp .part must not survive"
    assert seen[-1] == len(payload)


def test_download_rejects_digest_mismatch(tmp_path):
    """A tampered or corrupted body must never reach the path we would execute."""
    payload = b"MZ-tampered-payload"
    info = _info_for(payload, "sha256:" + "00" * 32)
    out = tmp_path / "r2sync-setup.exe"

    with patch("requests.get", return_value=_fake_stream(payload)):
        with pytest.raises(IntegrityError, match="integrity check"):
            AutoUpdater.download_update(info, target_path=out)

    assert not out.exists(), "failed download must not be left where it can be launched"
    assert not (tmp_path / "r2sync-setup.exe.part").exists()


def test_download_rejects_truncated_body(tmp_path):
    """A dropped connection yields fewer bytes than advertised -- reject, don't publish."""
    payload = b"MZ" + b"x" * 50
    info = _info_for(payload, None, size=len(payload) + 500)
    out = tmp_path / "r2sync-setup.exe"

    with patch("requests.get", return_value=_fake_stream(payload)):
        with pytest.raises(IntegrityError, match="truncated"):
            AutoUpdater.download_update(info, target_path=out)

    assert not out.exists()
    assert not (tmp_path / "r2sync-setup.exe.part").exists()


def test_download_cleans_up_part_file_on_network_error(tmp_path):
    """An exception mid-stream must not strand a partial file on disk."""
    payload = b"MZ" + b"y" * 40
    info = _info_for(payload, None)
    out = tmp_path / "r2sync-setup.exe"

    resp = _fake_stream(payload)
    resp.iter_content.side_effect = ConnectionError("connection reset")

    with patch("requests.get", return_value=resp):
        with pytest.raises(ConnectionError):
            AutoUpdater.download_update(info, target_path=out)

    assert not out.exists()
    assert not (tmp_path / "r2sync-setup.exe.part").exists()


def test_download_without_digest_still_checks_size(tmp_path):
    """No digest published -> size check alone must still let a good download through."""
    payload = b"MZ" + b"z" * 60
    info = _info_for(payload, None)
    out = tmp_path / "r2sync-setup.exe"

    with patch("requests.get", return_value=_fake_stream(payload)):
        path = AutoUpdater.download_update(info, target_path=out)

    assert path.read_bytes() == payload


def test_unsupported_digest_algorithm_degrades_gracefully(tmp_path):
    """An algorithm this Python cannot provide must not hard-fail the update."""
    payload = b"MZ" + b"q" * 30
    info = _info_for(payload, "notahash:deadbeef")
    out = tmp_path / "r2sync-setup.exe"

    with patch("requests.get", return_value=_fake_stream(payload)):
        path = AutoUpdater.download_update(info, target_path=out)

    assert path.read_bytes() == payload
