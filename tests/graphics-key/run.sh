#!/bin/sh
# Test: graphics-key (chroma-key cleanup in the claude-graphics image).
#
#   tests/graphics-key/run.sh
#
# 1. Runs test_graphics_key.py on this machine with the tool's built-in PNG code
#    (and with numpy and Pillow too, if this Python has them).
# 2. If the claude-graphics image exists (and podman can run it), runs the test
#    in it with the installed /usr/local/bin/graphics-key, once with the
#    built-in code and once with numpy and Pillow from PyPI (uv), so the image
#    and both backends are tested. The container needs network access to PyPI.
#
# Needs no sandbox, gateway or provider.
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
test_py=$root/tests/graphics-key/test_graphics_key.py

echo "-- on this machine"
GRAPHICS_KEY=$root/images/claude-graphics/graphics-key python3 "$test_py"

if command -v podman >/dev/null 2>&1 && podman image exists claude-graphics:latest 2>/dev/null; then
  echo "-- in the claude-graphics image, built-in code"
  podman run --rm -i -e GRAPHICS_KEY=/usr/local/bin/graphics-key localhost/claude-graphics:latest python3 - < "$test_py"
  echo "-- in the claude-graphics image, numpy and Pillow"
  podman run --rm -i -e GRAPHICS_KEY=/usr/local/bin/graphics-key localhost/claude-graphics:latest sh -c \
    'cd /tmp && uv venv -q .venv && uv pip install -q --python .venv/bin/python numpy pillow && .venv/bin/python -' < "$test_py"
else
  echo "-- the claude-graphics image is not built; skipping the tests in it (make claude-graphics)"
fi
echo "graphics-key: all tests passed"
