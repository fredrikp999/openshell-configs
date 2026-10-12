# Antigravity CLI (agy) sandbox image for OpenShell, for use with your Google
# account (e.g. a Google AI Pro/Ultra subscription).
#
#   podman build -t agy-sandbox:latest images/agy-sandbox    (or: make images)
#
# Debian with git, ripgrep and agy, installed with Google's install script,
# which checks the download against the release manifest's SHA-512. agy goes to
# /usr/local/bin/agy, the binary policies/antigravity.yaml lets reach Google.
# You log in inside the sandbox on first start (see docs/agents.md), and agy
# keeps its login in /sandbox. agy can't update itself: /usr is read-only in
# the sandbox and the update host isn't allowed; rebuild the image instead.
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates ripgrep curl \
 && curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- --dir /usr/local/bin \
 && rm -rf /root/.gemini /root/.cache /root/.config \
 && sed -i '/Antigravity CLI installer/,+1d' /root/.bashrc \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
