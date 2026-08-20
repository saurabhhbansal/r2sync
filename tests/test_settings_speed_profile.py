"""Regression test for the settings view re-saving the speed profile on every refresh.

``refresh_all_data()`` pushes the persisted speed profile back into the settings
view every few seconds. ``set_speed_profile()`` used to route that through the
same handler as a user dragging the slider, so the GUI rewrote the setting to
SQLite and logged "Speed profile updated to: turbo" continuously for as long as
the window was open, with nothing having changed.
"""

import os

import pytest

from conftest import skip_module_unless

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PySide6.QtWidgets import QApplication
    from r2sync.gui.views.settings_view import SettingsView
    PYSIDE6_AVAILABLE = True
except (ImportError, OSError) as e:  # pragma: no cover - environment dependent
    PYSIDE6_AVAILABLE = False
    PYSIDE6_IMPORT_ERROR = str(e)

pytestmark = skip_module_unless(
    PYSIDE6_AVAILABLE, "PySide6 runtime", "Install a PySide6 runtime (on Linux: libegl1, libgl1, libxkbcommon-x11-0, libdbus-1-3, libxcb-cursor0)."
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp):
    v = SettingsView()
    saves = []
    v.speed_profile_saved.connect(saves.append)
    return v, saves


def test_displaying_the_stored_profile_is_not_a_save(view):
    v, saves = view
    stored = v.speed_profiles_list[0].id

    for _ in range(5):
        v.set_speed_profile(stored)

    assert saves == [], (
        "reflecting stored state in the UI must not look like a user edit; "
        "each one cost a SQLite write and a log line every few seconds"
    )


def test_displaying_the_stored_profile_still_updates_the_card(view):
    v, _ = view
    target = v.speed_profiles_list[0]

    v.set_speed_profile(target.id)

    assert target.label in v.speed_title_lbl.text()
    assert str(target.transfers) in v.speed_metrics_lbl.text()


def test_the_user_moving_the_slider_still_saves(view):
    v, saves = view
    v.set_speed_profile(v.speed_profiles_list[0].id)
    saves.clear()

    # What a real drag emits.
    v.speed_slider.setValue(len(v.speed_profiles_list) - 1)

    assert saves == [v.speed_profiles_list[-1].id]
