"""Fail if the built wheel or sdist contains files that should never ship.

`uv build` copies from the working tree, not from git, so editor and OS
metadata that is gitignored but still present locally (`.DS_Store`, stray
`__pycache__` directories) can end up packaged. This is a narrow content
assertion, not a full release-validation pipeline (clean-environment install
and a CLI smoke test are tracked separately, see the safety model doc) — it
only checks for junk that has no business in a distribution regardless of
what else changes.

Usage: check_dist_contents.py [dist-dir]   (default: dist)
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

DISALLOWED_NAMES = {".DS_Store", "Thumbs.db"}
DISALLOWED_SUFFIXES = (".pyc", ".pyo")
DISALLOWED_DIR_SEGMENTS = {"__pycache__"}


def is_disallowed(member: str) -> bool:
    name = Path(member).name
    if name in DISALLOWED_NAMES or name.endswith(DISALLOWED_SUFFIXES):
        return True
    return bool(DISALLOWED_DIR_SEGMENTS & set(Path(member).parts))


def wheel_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def sdist_members(path: Path) -> list[str]:
    with tarfile.open(path) as archive:
        return archive.getnames()


def main() -> int:
    dist_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist")
    archives = sorted(dist_dir.glob("*.whl")) + sorted(dist_dir.glob("*.tar.gz"))
    if not archives:
        print(f"check-dist-contents: no archives found in {dist_dir}", file=sys.stderr)
        return 1

    failures: list[str] = []
    for archive in archives:
        members = wheel_members(archive) if archive.suffix == ".whl" else sdist_members(archive)
        failures.extend(
            f"{archive.name}: {member}" for member in members if is_disallowed(member)
        )

    if failures:
        print("check-dist-contents: disallowed files in distribution:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"check-dist-contents: {len(archives)} archive(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
