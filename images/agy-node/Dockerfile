# Antigravity CLI (agy) sandbox image that can install npm packages, for OpenShell.
#
#   podman build -t agy-node:latest images/agy-node    (or: make agy-node)
#
# Like images/agy-sandbox (agy at /usr/local/bin/agy, installed with Google's
# install script, and the community ACP adapter, started by agy-acp-start), but
# on node:22-slim, so Node.js is /usr/local/bin/node: the binary that
# policies/agy-node.yaml lets reach registry.npmjs.org. Use it with that policy
# (bin/sandbox.sh agy NAME --node). Python is not included.
FROM node:22-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates ripgrep curl \
 && curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- --dir /usr/local/bin \
 && npm install -g google-antigravity-acp@2.0.1 \
 && rm -rf /root/.gemini /root/.cache /root/.config /root/.npm \
 && sed -i '/Antigravity CLI installer/,+1d' /root/.bashrc \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
COPY --chmod=755 agy-acp-start /usr/local/bin/agy-acp-start
