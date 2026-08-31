#!/usr/bin/env python3
"""Validate the docs/ tree: broken relative links, broken heading anchors, and
orphan pages unreachable from mkdocs.yml's nav.

Generic template: works for any MkDocs site where mkdocs.yml's `nav` is the
single source of page structure. Generated-and-gitignored subtrees under
docs/ (e.g. TypeDoc/mkdocstrings output) are auto-detected from .gitignore
entries anchored under docs/ — pages under them may not exist until the doc
generators run, and links/anchors into them aren't checked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
MKDOCS_YML = ROOT / "mkdocs.yml"
GITIGNORE = ROOT / ".gitignore"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)


def strip_fenced_code(text: str) -> str:
    return FENCED_CODE_RE.sub("", text)


def slugify(header: str) -> str:
    header = re.sub(r"[`*]", "", header).strip().lower()
    header = re.sub(r"[^\w\s-]", "", header)
    return re.sub(r"\s+", "-", header)


def generated_prefixes() -> list[Path]:
    """Directories under docs/ that are gitignored — generator output, not
    handwritten. A nav entry or link pointing here may not exist pre-build."""
    if not GITIGNORE.exists():
        return []
    prefixes = []
    for line in GITIGNORE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = (ROOT / line.rstrip("/")).resolve()
        if DOCS_DIR in candidate.parents or candidate == DOCS_DIR:
            prefixes.append(candidate)
    return prefixes


GENERATED_PREFIXES = generated_prefixes()


def is_generated(path: Path) -> bool:
    return any(path == p or p in path.parents for p in GENERATED_PREFIXES)


def all_markdown_files() -> list[Path]:
    return sorted(p for p in DOCS_DIR.rglob("*.md") if not is_generated(p))


def anchors_in(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {slugify(h[1]) for h in HEADER_RE.findall(path.read_text())}


def nav_paths() -> list[str]:
    nav_config = yaml.safe_load(MKDOCS_YML.read_text())
    paths: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if node.endswith(".md"):
                paths.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(nav_config.get("nav", []))
    return paths


def check_links() -> list[str]:
    errors = []
    for path in all_markdown_files():
        text = strip_fenced_code(path.read_text())
        for link in LINK_RE.findall(text):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            target_part, _, anchor = link.partition("#")
            target_path = path if not target_part else (path.parent / target_part).resolve()
            if target_path.suffix and target_path.suffix != ".md":
                continue  # non-markdown asset (mockup .html, etc.) — not this check's job
            if not target_path.exists():
                if not is_generated(target_path):
                    errors.append(f"{path.relative_to(ROOT)}: broken link to {link!r}")
                continue
            if anchor and not is_generated(target_path) and anchor not in anchors_in(target_path):
                errors.append(f"{path.relative_to(ROOT)}: broken anchor in {link!r}")
    return errors


def linked_pages(path: Path) -> set[Path]:
    text = strip_fenced_code(path.read_text())
    targets = set()
    for link in LINK_RE.findall(text):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        target_part, _, _anchor = link.partition("#")
        if not target_part or not target_part.endswith(".md"):
            continue
        target_path = (path.parent / target_part).resolve()
        if target_path.exists():
            targets.add(target_path)
    return targets


def check_orphans() -> list[str]:
    """A page is reachable if it's in mkdocs.yml's nav, or linked to
    (transitively) from a page that is."""
    frontier = [(DOCS_DIR / p).resolve() for p in nav_paths() if (DOCS_DIR / p).resolve().exists()]
    reachable = set(frontier)
    while frontier:
        current = frontier.pop()
        for linked in linked_pages(current):
            if linked not in reachable:
                reachable.add(linked)
                frontier.append(linked)

    errors = []
    for path in all_markdown_files():
        if path.resolve() not in reachable:
            rel = path.relative_to(ROOT)
            errors.append(f"orphan page not reachable from mkdocs.yml nav: {rel}")
    return errors


def check_nav_targets_exist() -> list[str]:
    errors = []
    for nav_path in nav_paths():
        target = (DOCS_DIR / nav_path).resolve()
        if is_generated(target):
            continue
        if not target.exists():
            errors.append(f"mkdocs.yml nav references missing page: {nav_path!r}")
    return errors


def main() -> int:
    errors = check_nav_targets_exist() + check_orphans() + check_links()
    if errors:
        for error in errors:
            print(error)
        print(f"\n{len(errors)} docs check failure(s)")
        return 1
    print("docs check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
