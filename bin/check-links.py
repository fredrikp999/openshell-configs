#!/usr/bin/env python3
"""Check the links between the Markdown files of this repo.

  bin/check-links.py [FILE.md ...]

Without arguments, checks README.md and docs/*.md. For every relative link,
the file or folder must exist, and a #heading must match a heading in the
target file (GitHub's anchors: lowercase, punctuation removed, spaces as
hyphens, -1, -2, ... for repeated headings). Links to other sites (http,
https, mailto) aren't checked. Prints one line per broken link and exits 1
if there are any. Run by `make lint`.
Python 3.8+, standard library only.
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"(?<!!)\[(?:[^\]\[]|\[[^\]]*\])*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")


def lines_outside_code(text):
    """(line number, line) for the lines that aren't in a fenced code block."""
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield n, line


def slug(heading):
    """GitHub's anchor for a heading's text."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    s = s.replace("`", "").lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


_anchors = {}


def anchors(path):
    """The set of anchors of a Markdown file."""
    if path not in _anchors:
        found, seen = set(), {}
        with open(path, encoding="utf-8") as f:
            for _, line in lines_outside_code(f.read()):
                m = HEADING.match(line)
                if m:
                    base = slug(m.group(2))
                    n = seen.get(base, 0)
                    seen[base] = n + 1
                    found.add(base if n == 0 else f"{base}-{n}")
        _anchors[path] = found
    return _anchors[path]


def check(path):
    """Error messages for the broken links in one Markdown file."""
    errors = []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    rel = os.path.relpath(path, ROOT)
    for n, line in lines_outside_code(text):
        for m in LINK.finditer(INLINE_CODE.sub("", line)):
            target = m.group(1)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                continue
            file_part, _, anchor = target.partition("#")
            dest = os.path.normpath(os.path.join(os.path.dirname(path), file_part)) if file_part else path
            if not os.path.exists(dest):
                errors.append(f"{rel}:{n}: {target}: no such file or folder")
            elif anchor and dest.endswith(".md") and anchor not in anchors(dest):
                errors.append(f"{rel}:{n}: {target}: no heading #{anchor} in {os.path.relpath(dest, ROOT)}")
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n\n", 2)[2])
    p.add_argument("files", nargs="*", help="Markdown files (default: README.md and docs/*.md)")
    args = p.parse_args()
    files = args.files or [os.path.join(ROOT, "README.md")] + sorted(
        os.path.join(ROOT, "docs", f) for f in os.listdir(os.path.join(ROOT, "docs")) if f.endswith(".md"))
    errors = [e for f in files for e in check(os.path.abspath(f))]
    for e in errors:
        print(e)
    if errors:
        print(f"{len(errors)} broken link(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
