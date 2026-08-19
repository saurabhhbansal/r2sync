"""Unit tests for speed & concurrency profiles."""

from r2sync.core.speed_profiles import (
    SPEED_PROFILES,
    get_speed_profile,
    list_speed_profiles,
    DEFAULT_SPEED_PROFILE_ID,
)


def test_speed_profiles_list():
    profiles = list_speed_profiles()
    assert len(profiles) == 5
    ids = [p.id for p in profiles]
    assert ids == ["eco", "balanced", "fast", "turbo", "extreme"]


def test_get_speed_profile():
    turbo = get_speed_profile("turbo")
    assert turbo.transfers == 32
    assert turbo.checkers == 32
    assert turbo.buffer_size == "32M"

    eco = get_speed_profile("eco")
    assert eco.transfers == 4
    assert eco.checkers == 4

    fallback = get_speed_profile("nonexistent_profile")
    assert fallback.id == DEFAULT_SPEED_PROFILE_ID
