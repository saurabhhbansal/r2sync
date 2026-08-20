#!/usr/bin/env python3
"""Verify every place the version is written agrees, and matches the git tag.

r2sync spells its version in three files plus the tag that triggers a release.
They drifted once already: a release went out with ``config.APP_VERSION`` left
on the previous number, which the IPC ``ping`` reply reports and which the
updater compares against GitHub -- so every user of that build was told an
update was available for the version they were already running.

Run before tagging::

    python packaging/check_version.py            # the files must agree
    python packaging/check_version.py v1.2.4     # ...and match this tag
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # tomllib is 3.11+; requires-python allows 3.10
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent


def _read(label: str, path: Path, pattern: str) -> tuple[str, str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text)
    if not match:
        raise SystemExit(f"could not find a version in {path.relative_to(ROOT)}")
    return label, str(path.relative_to(ROOT)), match.group(1)


def _pyproject_version() -> str:
    """``project.version`` from pyproject.toml, with or without tomllib.

    This script runs before anything is installed and must work on every
    interpreter the project supports, so 3.10 -- which has no tomllib -- falls
    back to reading the key out of the ``[project]`` table itself rather than
    taking a dependency on tomli.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)["project"]["version"]

    table = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not table:
        raise SystemExit("could not find a [project] table in pyproject.toml")
    match = re.search(r'^version\s*=\s*"([^"]+)"', table.group(1), re.M)
    if not match:
        raise SystemExit("could not find project.version in pyproject.toml")
    return match.group(1)


def collect() -> list[tuple[str, str, str]]:
    """Every version string in the repo, as (label, file, value)."""
    return [
        _read("__version__", ROOT / "src/r2sync/__init__.py",
              r'__version__\s*=\s*"([^"]+)"'),
        ("project.version", "pyproject.toml", _pyproject_version()),
        _read("MyAppVersion", ROOT / "packaging/installer.iss",
              r'#define\s+MyAppVersion\s+"([^"]+)"'),
    ]


def main(argv: list[str]) -> int:
    versions = collect()
    width = max(len(label) for label, _, _ in versions)
    for label, path, value in versions:
        print(f"  {label:<{width}}  {value:<12} ({path})")

    distinct = {value for _, _, value in versions}
    if len(distinct) != 1:
        print(f"\nFAIL: version strings disagree: {sorted(distinct)}", file=sys.stderr)
        print("Bump all of them together, then re-run.", file=sys.stderr)
        return 1

    version = distinct.pop()

    # config.APP_VERSION is derived from __init__ rather than hand-written, but
    # assert it anyway -- that derivation is exactly what regressed before.
    sys.path.insert(0, str(ROOT / "src"))
    from r2sync.config import APP_VERSION  # noqa: E402

    if APP_VERSION != version:
        print(f"\nFAIL: config.APP_VERSION is {APP_VERSION!r}, expected {version!r}",
              file=sys.stderr)
        return 1
    print(f"  {'APP_VERSION':<{width}}  {APP_VERSION:<12} (derived at import)")

    tag = argv[1] if len(argv) > 1 else None
    if tag:
        expected = tag[1:] if tag.startswith("v") else tag
        if expected != version:
            print(f"\nFAIL: tag {tag!r} does not match version {version!r}",
                  file=sys.stderr)
            return 1
        print(f"\nOK: version {version} matches tag {tag}")
    else:
        print(f"\nOK: version {version} is consistent everywhere")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
