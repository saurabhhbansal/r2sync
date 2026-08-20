"""Speed and concurrency profiles for r2sync transfer engine.

Each profile carries *both* directions. The upload knobs (``chunk_size``,
``upload_concurrency``) only affect S3 multipart PUTs; downloads from R2 are
governed by a completely separate set of rclone flags
(``--multi-thread-cutoff`` / ``--multi-thread-streams`` /
``--multi-thread-chunk-size``). Leaving those at rclone's defaults means a
file under 256 MiB is fetched over a *single* HTTP stream no matter how fast
the link is, which is why downloads used to lag uploads badly.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class SpeedProfile:
    id: str
    label: str
    transfers: int
    checkers: int
    chunk_size: str
    buffer_size: str
    description: str
    # --- download side -------------------------------------------------
    # Files larger than multi_thread_cutoff are fetched with
    # multi_thread_streams parallel range requests.
    multi_thread_streams: int = 4
    multi_thread_cutoff: str = "32M"
    multi_thread_chunk_size: str = "32M"
    # --- upload side ---------------------------------------------------
    upload_concurrency: int = 8
    # Objects fetched per S3 LIST call while enumerating the remote.
    list_chunk: int = 1000

    @property
    def effective_multi_thread_streams(self) -> int:
        """Cap parallel download streams so transfers x streams stays sane.

        ``--transfers`` files are in flight at once and each may open
        ``--multi-thread-streams`` sockets. Left unbounded a "turbo" profile
        would ask for 32 x 8 = 256 concurrent range requests, which saturates
        the local disk's write queue long before it helps throughput.
        """
        cpu = os.cpu_count() or 4
        return max(2, min(self.multi_thread_streams, cpu * 2))


SPEED_PROFILES: Dict[str, SpeedProfile] = {
    "eco": SpeedProfile(
        id="eco",
        label="Low (Eco)",
        transfers=4,
        checkers=8,
        chunk_size="8M",
        buffer_size="8M",
        description="Low CPU & memory usage. Ideal for battery power or metered connections.",
        multi_thread_streams=2,
        multi_thread_cutoff="128M",
        multi_thread_chunk_size="16M",
        upload_concurrency=4,
        list_chunk=1000,
    ),
    "balanced": SpeedProfile(
        id="balanced",
        label="Medium (Balanced)",
        transfers=8,
        checkers=16,
        chunk_size="16M",
        buffer_size="16M",
        description="Default balanced profile. Good mix of speed and resource efficiency.",
        multi_thread_streams=4,
        multi_thread_cutoff="64M",
        multi_thread_chunk_size="32M",
        upload_concurrency=4,
        list_chunk=1000,
    ),
    "fast": SpeedProfile(
        id="fast",
        label="High (Fast)",
        transfers=16,
        checkers=32,
        chunk_size="16M",
        buffer_size="32M",
        description="Optimized for high-speed broadband connections (100-300 Mbps).",
        multi_thread_streams=4,
        multi_thread_cutoff="32M",
        multi_thread_chunk_size="32M",
        upload_concurrency=8,
        list_chunk=1000,
    ),
    "turbo": SpeedProfile(
        id="turbo",
        label="X-High (Turbo)",
        transfers=32,
        checkers=64,
        chunk_size="16M",
        buffer_size="32M",
        description="Ultra-fast parallel transfers (32 streams). Ideal for 500+ Mbps or gigabit fiber.",
        multi_thread_streams=8,
        multi_thread_cutoff="32M",
        multi_thread_chunk_size="32M",
        upload_concurrency=16,
        list_chunk=1000,
    ),
    "extreme": SpeedProfile(
        id="extreme",
        label="Extreme (Max)",
        transfers=64,
        checkers=128,
        chunk_size="32M",
        buffer_size="64M",
        description="Maximum throughput (64 streams). Full multi-threaded line saturation.",
        multi_thread_streams=8,
        multi_thread_cutoff="32M",
        multi_thread_chunk_size="64M",
        upload_concurrency=32,
        list_chunk=1000,
    ),
}

DEFAULT_SPEED_PROFILE_ID = "turbo"


def get_speed_profile(profile_id: Optional[str] = None) -> SpeedProfile:
    """Retrieve speed profile by ID, falling back to default."""
    if profile_id and profile_id.lower() in SPEED_PROFILES:
        return SPEED_PROFILES[profile_id.lower()]
    return SPEED_PROFILES[DEFAULT_SPEED_PROFILE_ID]


def list_speed_profiles() -> List[SpeedProfile]:
    """List all available speed profiles in order of performance."""
    return list(SPEED_PROFILES.values())


def build_transfer_flags(prof: SpeedProfile, include_s3: bool = True) -> List[str]:
    """Build the rclone flags shared by upload and download paths.

    Kept in one place so the backup (upload-only) and bisync (bidirectional)
    code paths cannot drift apart again.
    """
    flags = [
        "--buffer-size", prof.buffer_size,
        "--transfers", str(prof.transfers),
        "--checkers", str(prof.checkers),
        # Download tuning: without these, any file below rclone's 256 MiB
        # default cutoff comes down over a single stream.
        "--multi-thread-streams", str(prof.effective_multi_thread_streams),
        "--multi-thread-cutoff", prof.multi_thread_cutoff,
        "--multi-thread-chunk-size", prof.multi_thread_chunk_size,
        "--retries", "3",
        "--low-level-retries", "10",
    ]
    if include_s3:
        flags += [
            "--s3-chunk-size", prof.chunk_size,
            "--s3-upload-cutoff", prof.chunk_size,
            "--s3-copy-cutoff", prof.chunk_size,
            "--s3-upload-concurrency", str(prof.upload_concurrency),
            "--s3-list-chunk", str(prof.list_chunk),
            "--s3-no-check-bucket",
            "--s3-disable-checksum",
        ]
    return flags
