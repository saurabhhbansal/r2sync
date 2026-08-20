"""Automated update checker and seamless installer for r2sync."""

import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from r2sync.config import APP_VERSION, GITHUB_RELEASES_API, GITHUB_REPO
from r2sync.utils.paths import get_cache_dir

logger = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    available: bool
    current_version: str
    latest_version: str
    release_name: str
    release_notes: str
    download_url: Optional[str] = None
    asset_name: Optional[str] = None
    asset_size: int = 0
    asset_digest: Optional[str] = None
    published_at: Optional[str] = None
    html_url: Optional[str] = None


def parse_version_tuple(ver_str: str) -> tuple:
    """Parse version string like 'v1.2.3' or '1.2.3' into (1, 2, 3)."""
    cleaned = re.sub(r"^[^\d]*", "", ver_str.strip())
    parts = []
    for piece in cleaned.split("."):
        digits = re.findall(r"\d+", piece)
        parts.append(int(digits[0]) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


class IntegrityError(Exception):
    """Raised when a downloaded update does not match its published size or digest."""


def _new_hasher(digest: Optional[str]):
    """Build a hasher for an 'algo:hex' digest string.

    Returns (hasher, expected_hex), or (None, None) when the release published no
    digest or names an algorithm this Python build cannot provide.
    """
    if not digest or ":" not in digest:
        return None, None
    algo, _, expected = digest.partition(":")
    try:
        return hashlib.new(algo.strip().lower()), expected.strip().lower()
    except ValueError:
        logger.warning(f"Unsupported digest algorithm {algo!r}; skipping hash verification.")
        return None, None


class AutoUpdater:
    """Handles checking, downloading, and applying application updates."""

    @staticmethod
    def check_for_updates(timeout: float = 5.0) -> UpdateInfo:
        """Query GitHub Releases API to see if a newer version is published."""
        curr_ver = APP_VERSION
        info = UpdateInfo(
            available=False,
            current_version=curr_ver,
            latest_version=curr_ver,
            release_name="",
            release_notes="",
            html_url=f"https://github.com/{GITHUB_REPO}/releases/latest",
        )

        try:
            resp = requests.get(
                GITHUB_RELEASES_API,
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": f"r2sync/{curr_ver}"},
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.debug(f"GitHub release check returned status {resp.status_code}")
                return info

            data = resp.json()
            tag_name = data.get("tag_name", "").strip()
            latest_ver = tag_name.lstrip("v")
            curr_tuple = parse_version_tuple(curr_ver)
            latest_tuple = parse_version_tuple(latest_ver)

            is_newer = latest_tuple > curr_tuple

            assets = data.get("assets", [])
            chosen_asset = None

            # Look for Windows installer asset or platform bundle
            if sys.platform == "win32":
                for asset in assets:
                    name = asset.get("name", "").lower()
                    if name.endswith(".exe") or "setup" in name or "installer" in name:
                        chosen_asset = asset
                        break
            if not chosen_asset and assets:
                chosen_asset = assets[0]

            download_url = chosen_asset.get("browser_download_url") if chosen_asset else None
            asset_size = chosen_asset.get("size", 0) if chosen_asset else 0
            asset_name = chosen_asset.get("name", "") if chosen_asset else ""
            asset_digest = chosen_asset.get("digest") if chosen_asset else None

            return UpdateInfo(
                available=is_newer,
                current_version=curr_ver,
                latest_version=latest_ver,
                release_name=data.get("name", f"Release {tag_name}"),
                release_notes=data.get("body", "No release notes provided."),
                download_url=download_url,
                asset_name=asset_name,
                asset_size=asset_size,
                asset_digest=asset_digest,
                published_at=data.get("published_at"),
                html_url=data.get("html_url", info.html_url),
            )

        except Exception as e:
            logger.debug(f"Update check failed: {e}")
            return info

    @staticmethod
    def download_update(
        update_info: UpdateInfo,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        target_path: Optional[Path] = None,
    ) -> Path:
        """Download the update asset, verify it, and only then publish it at out_path.

        Bytes land in a sibling .part file, so a dropped connection can never leave a
        truncated installer where apply_update_windows would find and launch it. The
        .part is promoted to out_path only once both the size and the digest GitHub
        published for the asset match what actually arrived.
        """
        if not update_info.download_url:
            raise ValueError("No download URL available for this update.")

        dest_dir = get_cache_dir() / "updates"
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = update_info.asset_name or f"r2sync-setup-{update_info.latest_version}.exe"
        out_path = target_path or (dest_dir / filename)
        part_path = out_path.with_name(out_path.name + ".part")

        hasher, expected_digest = _new_hasher(update_info.asset_digest)
        if hasher is None:
            logger.warning("Release published no usable digest; falling back to a size check only.")

        try:
            with requests.get(update_info.download_url, stream=True, timeout=60.0) as r:
                r.raise_for_status()
                total_bytes = int(r.headers.get("content-length", update_info.asset_size or 0))
                downloaded = 0

                with open(part_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            if hasher is not None:
                                hasher.update(chunk)
                            downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(downloaded, total_bytes)

            expected_size = update_info.asset_size or total_bytes
            if expected_size and downloaded != expected_size:
                raise IntegrityError(
                    f"Update download truncated: got {downloaded} bytes, expected {expected_size}."
                )

            if hasher is not None:
                actual_digest = hasher.hexdigest()
                if actual_digest != expected_digest:
                    raise IntegrityError(
                        f"Update failed its integrity check: {hasher.name} was {actual_digest}, "
                        f"expected {expected_digest}. Refusing to install."
                    )

            os.replace(part_path, out_path)
            return out_path

        except BaseException:
            part_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def apply_update_windows(installer_path: Path, silent: bool = True) -> bool:
        """Launch downloaded Windows installer and signal current app to terminate."""
        if not installer_path.exists():
            return False

        try:
            cmd = [str(installer_path)]
            if silent:
                cmd.extend(["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"])

            flags = 0x08000000 if sys.platform == "win32" else 0
            subprocess.Popen(cmd, creationflags=flags)
            return True
        except Exception as e:
            logger.error(f"Failed to launch update installer: {e}")
            return False
