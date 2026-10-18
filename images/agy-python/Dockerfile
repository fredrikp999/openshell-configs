# Antigravity CLI (agy) sandbox image with Python and pip, for OpenShell.
#
#   podman build -t agy-python:latest images/agy-python    (or: make agy-python)
#
# Builds on agy-sandbox (agy at /usr/local/bin/agy and the community ACP
# adapter, agy-acp-start) and adds Python 3 from Debian with pip and venv.
# Debian's pip refuses system-wide installs, so packages go in a venv:
# python -m venv .venv. Use it with policies/agy-python.yaml, which lets
# Python reach PyPI read-only (bin/sandbox.sh agy-python).
FROM localhost/agy-sandbox:latest
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip python3-venv python-is-python3 \
 && rm -rf /var/lib/apt/lists/*
