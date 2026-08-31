#!/usr/bin/env python3
"""Unwrap one Markdown file in place: one line per block (paragraph/list item).

Preserved verbatim: YAML front matter, fenced code, tables, headings, blank lines.
Verified: the whitespace-normalised document must be identical before and after.
"""
import re
import sys
import pathlib

MARKER = re.compile(r'^(\s*)([-*+]|\d+\.)\s+')
VERBATIM = re.compile(r'^(#{1,6}\s|\||```|>)')


def unwrap(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(lines)

    def flush() -> None:
        if buf:
            out.append(" ".join(s.strip() for s in buf))
            buf.clear()

    if lines and lines[0].strip() == "---":
        out.append(lines[0])
        i = 1
        while i < n and lines[i].strip() != "---":
            out.append(lines[i])
            i += 1
        if i < n:
            out.append(lines[i])
            i += 1

    in_fence = False
    while i < n:
        ln = lines[i]
        if ln.lstrip().startswith("```"):
            flush()
            out.append(ln)
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            out.append(ln)
            i += 1
            continue
        if not ln.strip():
            flush()
            out.append("")
            i += 1
            continue
        if VERBATIM.match(ln):
            flush()
            out.append(ln.rstrip())
            i += 1
            continue
        m = MARKER.match(ln)
        if m:
            flush()
            indent = m.group(1)
            parts: list[str] = [ln.strip()]
            i += 1
            while i < n:
                nxt = lines[i]
                if (
                    not nxt.strip()
                    or VERBATIM.match(nxt)
                    or MARKER.match(nxt)
                    or nxt.lstrip().startswith("```")
                ):
                    break
                parts.append(nxt.strip())
                i += 1
            out.append(indent + " ".join(parts))
            continue
        buf.append(ln)
        i += 1
    flush()
    return re.sub(r'\n{3,}', '\n\n', "\n".join(out))


def norm(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


def main() -> None:
    if len(sys.argv) != 2:
        return
    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        return
    src = path.read_text()
    if re.search(r'\S  +\n', src):
        print(f"unwrap: {path.name}: hard line break present — skipped", file=sys.stderr)
        return
    dst = unwrap(src)
    if norm(src) != norm(dst):
        print(f"unwrap: {path.name}: CONTENT DRIFT — not written", file=sys.stderr)
        return
    if src != dst:
        path.write_text(dst)
        print(f"unwrap: {path.name}: unwrapped")


if __name__ == "__main__":
    main()
