#!/bin/sh
# Test: artcraft-key (chroma-key cleanup in the claude-artcraft image).
#
#   tests/artcraft-key/run.sh
#
# 1. Runs test_artcraft_key.py on this machine with the tool's built-in PNG code
#    (and with numpy and Pillow too, if this Python has them).
# 2. If the claude-artcraft image exists (and podman can run it), runs the test
#    in it with the installed /usr/local/bin/artcraft-key, once with the
#    built-in code and once with numpy and Pillow from PyPI (uv), so the image
#    and both backends are tested. The container needs network access to PyPI.
#
# Needs no sandbox, gateway or provider.
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
test_py=$root/tests/artcraft-key/test_artcraft_key.py

echo "-- on this machine"
ARTCRAFT_KEY=$root/images/claude-artcraft/artcraft-key python3 "$test_py"

if command -v podman >/dev/null 2>&1 && podman image exists claude-artcraft:latest 2>/dev/null; then
  echo "-- in the claude-artcraft image, built-in code"
  podman run --rm -i -e ARTCRAFT_KEY=/usr/local/bin/artcraft-key localhost/claude-artcraft:latest python3 - < "$test_py"
  echo "-- in the claude-artcraft image, numpy and Pillow"
  podman run --rm -i -e ARTCRAFT_KEY=/usr/local/bin/artcraft-key localhost/claude-artcraft:latest sh -c \
    'cd /tmp && uv venv -q .venv && uv pip install -q --python .venv/bin/python numpy pillow && .venv/bin/python -' < "$test_py"
else
  echo "-- the claude-artcraft image is not built; skipping the tests in it (make claude-artcraft)"
fi
echo "artcraft-key: all tests passed"
