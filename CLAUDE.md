# r2sync — working notes for Claude

Native, private, open-source backup and multi-PC folder sync for Cloudflare R2.
Python + PySide6 GUI, a background service, and rclone underneath. Ships as a
Windows installer built by GitHub Actions.

## Standing instructions

- **Always commit after making changes.** Don't leave work uncommitted.
- **Only push when I say so.** Never `git push` on your own.
- **Bump the version as part of the change** so the release workflow can run on
  the resulting tag. See [Releasing](#releasing) for the exact files.
- Branch off `main` for anything non-trivial; `main` is the default branch and
  the base for PRs.

## Layout

```
src/r2sync/
  config.py            constants; APP_VERSION derives from __init__.py
  core/                db.py, sync_engine.py, rclone_engine.py, scheduler.py,
                       watcher.py, backup_engine.py, prescan.py, updater.py
  gui/                 PySide6 app; app.py is MainWindow, views/ the screens
  service/             background daemon + IPC server
  client/              IPC client, CLI (r2sync-cli), TUI
packaging/             installer.iss, build_installer.py, check_version.py
tests/                 pytest suite; conftest.py holds the shared fixtures
```

Entry points: `r2sync` (GUI), `r2sync-service`, `r2sync-cli`.

## Running things

```bash
pip install -e .[dev]

# Full suite. QT_QPA_PLATFORM=offscreen is required for the GUI tests.
QT_QPA_PLATFORM=offscreen pytest -q

# The end-to-end tests need a real rclone binary and skip themselves without one.
R2SYNC_TEST_RCLONE=/path/to/rclone QT_QPA_PLATFORM=offscreen pytest -q

# What CI runs: a missing optional dependency becomes a hard failure.
R2SYNC_REQUIRE_FULL_SUITE=1 QT_QPA_PLATFORM=offscreen pytest -v -rs
```

Expect **162 passed, 1 skipped** on Linux with rclone present. The one skip is
`test_service_restore.py::…` — a Windows-registry test that runs on the Windows
CI leg.

### Test environment variables

| Variable | Effect |
|---|---|
| `R2SYNC_TEST_RCLONE` | Path to the rclone binary for `test_sync_e2e.py`. Falls back to `rclone` on PATH. |
| `R2SYNC_REQUIRE_FULL_SUITE=1` | Turns dependency-gated skips into errors. Set by both workflows. |
| `R2SYNC_DATA_DIR` | Throwaway app-data dir. `conftest.py` sets one per test automatically. |
| `R2SYNC_NO_AUTO_SERVICE=1` | Stops `MainWindow` spawning a real daemon. Set in `conftest.py`. |
| `QT_QPA_PLATFORM=offscreen` | Required for any GUI test outside a desktop session. |

`tests/test_sync_e2e.py` runs the whole production path — watcher, debounce,
coalescing queue, SyncEngine, the real bisync command line, progress parsing —
against an rclone `alias:` remote pointing at a second local directory, so no
credentials are needed. Only the storage backend is swapped.

## GitHub Actions

Two workflows. Both install rclone themselves, at the version read from
`r2sync.config.RCLONE_VERSION`, so CI exercises the same binary users get.

### `.github/workflows/ci.yml` — "CI Tests"

- **Triggers:** push to `main`/`master`, PRs targeting `main`/`master`,
  `workflow_dispatch`.
- **Concurrency:** `ci-<ref>`, cancel-in-progress.
- **Matrix:** `ubuntu-latest` + `windows-latest` × Python `3.10`, `3.11`, `3.12`.
  `fail-fast: false`, 20-minute timeout.
- **Steps:** checkout → setup-python (pip cache) → Qt system libs on Linux →
  `pip install -e .[dev]` → `packaging/check_version.py` → install rclone →
  `rclone version` → `pytest -v -rs`.
- Test step sets `QT_QPA_PLATFORM=offscreen` and `R2SYNC_REQUIRE_FULL_SUITE=1`.

### `.github/workflows/release.yml` — "Release Windows Installer"

- **Triggers:** push of a tag matching `v*`, or `workflow_dispatch`.
- **Runs on:** `windows-latest`, 45-minute timeout, `permissions: contents: write`.
- **Concurrency:** `release-<ref>`, cancel-in-progress.
- **Steps:** checkout → setup-python 3.12 → `pip install -e .[dev]` + pyinstaller
  → install rclone → `rclone version` → `check_version.py "$GITHUB_REF_NAME"`
  (compares against the tag; on `workflow_dispatch` it only checks the files
  agree with each other) → `pytest -v -rs` → `choco install innosetup` →
  `python packaging/build_installer.py` → upload `dist/r2sync-setup.exe` as an
  artifact (`if-no-files-found: error`) → `softprops/action-gh-release@v2`,
  which publishes a non-draft release with generated notes. The publish step is
  guarded on `refs/tags/v`, so a `workflow_dispatch` run builds and uploads the
  artifact without cutting a release.

**A tag is what ships a release.** Pushing to `main` only runs CI.

## Releasing

The version lives in three files that must agree. `config.APP_VERSION` derives
from `__init__.py`, so don't add a fourth by hand.

1. `src/r2sync/__init__.py` — `__version__` (the source of truth)
2. `pyproject.toml` — `project.version`
3. `packaging/installer.iss` — `#define MyAppVersion`

```bash
python packaging/check_version.py          # the files agree
python packaging/check_version.py v1.2.4   # ...and match the tag you're about to push
git commit -am "release: bump to v1.2.4"
git push                                   # only when I say so
git tag v1.2.4 && git push origin v1.2.4   # this is what triggers the release
```

`check_version.py` runs in both workflows, so a mismatch fails the build rather
than shipping an installer whose in-app version disagrees with its own tag —
which makes the updater offer users the build they are already running.

## Things that bite

- **rclone's bisync output needs precise matching.** It prints a *generic*
  footer (`Bisync aborted. Must run --resync to recover.`) after every critical
  error and every interruption. Matching the bare `must run --resync` substring
  reported unrelated failures as a stale baseline and triggered pointless full
  re-baselines. Only the specific diagnostics in `_STALE_BASELINE_MARKERS`
  (`rclone_engine.py`) mean the workdir listings are actually unusable, and
  `Empty prior Path1 listing` vs `Empty current Path1 listing` are opposite
  situations rendered from one format string — never key off their shared tail.
- **Never touch a widget from a worker thread.** Sync callbacks run on a sync
  worker and IPC events on the socket-reader thread. Route them through the
  `*_received` signals on `MainWindow`; Qt then runs the handler on the GUI
  thread. Doing it directly segfaults the process mid-sync — intermittently, so
  it looks like flakiness. `tests/test_gui_thread_safety.py` guards this.
- **`db.update_sync_status(last_error=...)` uses a sentinel.** Passing `None`
  *clears* the column; omitting the argument leaves it alone. They used to be
  the same thing, so a successful sync could never shed a previous error.
- **The GUI polls `refresh_all_data()` every 5s.** Anything it pushes into a
  view must not look like a user edit — `set_speed_profile()` re-emitting its
  "saved" signal caused a SQLite write and a log line every few seconds, all day.
- **`git worktree add` resolves relative paths against the repo root.** Use an
  absolute path or you'll create a worktree inside the working tree.
