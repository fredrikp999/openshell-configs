#!/usr/bin/env python3
"""Let Kiro Crew's no-follow path walks start below / when / cannot be opened.

Kiro Crew pins a path by opening / and then each component through the previous
descriptor (O_NOFOLLOW). OpenShell's Landlock baseline grants the children of /
but never / itself, so os.open("/") fails with EACCES in the sandbox and anything
that pins a path breaks: app backends ("Failed to serialize dependency
provisioning ... Permission denied: '/'"), project skills and the pycache sweep.

The patch makes each walk start at the first path component (e.g. /opt, /sandbox)
when / is unreadable. The components below are still opened one by one with
O_NOFOLLOW. Only the first, root-owned component is opened by name, and a sandboxed
process cannot swap that for a link.

Run at image build:  patch-unreadable-root.py <kiro_crew package dir>
It fails the build if a call site is not found exactly once, so a Kiro Crew update
that changes these files is noticed instead of silently half-patched.
Left alone: apps/builtins/dev_fleet/repository.py (only discards untracked files
in a worktree).
"""
import sys
from pathlib import Path

HELPER = '''
def _skip_unreadable_root(parts):
    # openshell-configs patch: see images/claude-kirocrew/patch-unreadable-root.py
    import os as _os
    if len(parts) > 1 and parts[0] == _os.sep:
        try:
            _os.close(_os.open(parts[0], _os.O_RDONLY | getattr(_os, "O_DIRECTORY", 0)))
        except PermissionError:
            return (_os.path.join(parts[0], parts[1]), *parts[2:])
    return parts

'''

# file -> (text to find once, text to put in its place)
SITES = {
    "pinned_fs.py": (
        "    if os.path.isabs(resolved_parent):\n        dir_fd = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)\n",
        "    parts = _skip_unreadable_root(parts)\n"
        "    if os.path.isabs(resolved_parent):\n        dir_fd = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)\n",
    ),
    "pycache_gc.py": (
        "    parts = Path(os.path.abspath(root)).parts\n    try:\n        fd = os.open(parts[0], _DIR_OPEN_FLAGS)\n",
        "    parts = _skip_unreadable_root(Path(os.path.abspath(root)).parts)\n    try:\n        fd = os.open(parts[0], _DIR_OPEN_FLAGS)\n",
    ),
    "skills.py": (
        "    parts = Path(os.path.abspath(base)).parts\n    try:\n        fd = os.open(parts[0], _PROJECT_DIR_OPEN_FLAGS)\n",
        "    parts = _skip_unreadable_root(Path(os.path.abspath(base)).parts)\n    try:\n        fd = os.open(parts[0], _PROJECT_DIR_OPEN_FLAGS)\n",
    ),
}

pkg = Path(sys.argv[1])
for name, (old, new) in SITES.items():
    path = pkg / name
    text = path.read_text()
    if text.count(old) != 1:
        sys.exit(f"{name}: expected the call site exactly once, found {text.count(old)}; Kiro Crew changed, update this patch")
    if "_skip_unreadable_root" in text.replace(new, ""):
        sys.exit(f"{name}: already patched")
    text = text.replace(old, new)
    # Appended: it is only called at run time, after the module has loaded.
    text = text.rstrip("\n") + "\n\n" + HELPER.strip("\n") + "\n"
    path.write_text(text)
    print(f"patched {name}")
