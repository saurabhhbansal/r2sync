"""Speed and concurrency profiles for r2sync transfer engine."""

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


SPEED_PROFILES: Dict[str, SpeedProfile] = {
    "eco": SpeedProfile(
        id="eco",
        label="Low (Eco)",
        transfers=4,
        checkers=8,
        chunk_size="8M",
        buffer_size="8M",
        description="Low CPU & memory usage. Ideal for battery power or metered connections.",
    ),
    "balanced": SpeedProfile(
        id="balanced",
        label="Medium (Balanced)",
        transfers=8,
        checkers=16,
        chunk_size="16M",
        buffer_size="16M",
        description="Default balanced profile. Good mix of speed and resource efficiency.",
    ),
    "fast": SpeedProfile(
        id="fast",
        label="High (Fast)",
        transfers=16,
        checkers=32,
        chunk_size="16M",
        buffer_size="32M",
        description="Optimized for high-speed broadband connections (100–300 Mbps).",
    ),
    "turbo": SpeedProfile(
        id="turbo",
        label="X-High (Turbo)",
        transfers=32,
        checkers=64,
        chunk_size="16M",
        buffer_size="32M",
        description="Ultra-fast parallel transfers (32 streams). Ideal for 500+ Mbps or gigabit fiber.",
    ),
    "extreme": SpeedProfile(
        id="extreme",
        label="Extreme (Max)",
        transfers=64,
        checkers=128,
        chunk_size="32M",
        buffer_size="64M",
        description="Maximum throughput (64 streams). Full multi-threaded line saturation.",
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
