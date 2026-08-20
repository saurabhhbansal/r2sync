"""Shared pytest configuration for the r2sync suite."""

import os

import pytest

# CI sets this. Several test modules are gated on an optional dependency being
# present (a PySide6 runtime, an rclone binary) and skip themselves when it is
# not -- which is right for a contributor's laptop but was hiding whole
# suites in CI: the end-to-end tests never ran once on main or on any release
# tag, and the job still went green. With this set, a missing dependency is a
# hard failure that names what to install instead of a silent skip.
REQUIRE_FULL_SUITE = os.environ.get("R2SYNC_REQUIRE_FULL_SUITE") == "1"


def require_or_skip(available: bool, what: str, how_to_install: str) -> None:
    """Skip when an optional dependency is missing -- unless we are in CI.

    Call from a module-level guard or a fixture. ``what`` names the missing
    dependency and ``how_to_install`` tells the reader how to get it.
    """
    if available:
        return
    message = f"{what} is unavailable. {how_to_install}"
    if REQUIRE_FULL_SUITE:
        raise RuntimeError(
            f"R2SYNC_REQUIRE_FULL_SUITE=1 but {message} "
            "Install it in the workflow rather than letting these tests skip."
        )
    pytest.skip(message)


def skip_module_unless(available: bool, what: str, how_to_install: str):
    """Module-level ``pytestmark`` form of :func:`require_or_skip`."""
    if REQUIRE_FULL_SUITE and not available:
        raise RuntimeError(
            f"R2SYNC_REQUIRE_FULL_SUITE=1 but {what} is unavailable. "
            f"{how_to_install} "
            "Install it in the workflow rather than letting these tests skip."
        )
    return pytest.mark.skipif(not available, reason=f"{what} unavailable. {how_to_install}")

# Constructing the GUI window normally launches the detached background service
# (that is what keeps sync alive after the window closes). Tests must never
# spawn a real daemon, which would bind the IPC port and outlive the run.
os.environ.setdefault("R2SYNC_NO_AUTO_SERVICE", "1")


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path_factory, monkeypatch):
    """Point every test at a throwaway application data directory."""
    if os.environ.get("R2SYNC_DATA_DIR"):
        yield
        return
    data_dir = tmp_path_factory.mktemp("r2sync-data")
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(data_dir))
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Record each phase's report on the item so fixtures can see the outcome.

    Teardown normally cannot tell a passing test from a failing one, which is
    what :func:`tests.test_sync_e2e.harness` needs in order to dump rclone's
    own log only when something actually went wrong.
    """
    outcome = yield
    setattr(item, f"rep_{outcome.get_result().when}", outcome.get_result())
