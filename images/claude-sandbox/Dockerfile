# Claude Code sandbox image for OpenShell.
#
#   podman build -t claude-sandbox:latest images/claude-sandbox    (or: make images)
#
# Start it with `-- claude-start` instead of `-- claude`. On first start,
# claude-start copies /etc/claude-start.json to $HOME/.claude.json (/sandbox,
# which starts empty), which marks onboarding as completed. Images built on
# this one (images/claude-browser) can replace that file, e.g. to add MCP
# servers. Onboarding runs a connectivity check that bypasses the OpenShell
# proxy and is denied, so Claude Code would exit with
# "Failed to connect to api.anthropic.com: EACCES".
# For ACP (sandbox.sh --acp, acp_client.py --agent claude) use claude-acp-start.
FROM node:22-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code @agentclientprotocol/claude-agent-acp
# No telemetry, error reporting or auto-updates. Their hosts are not in the
# claude-code-oauth profile, so the requests would only be denied.
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
# ACP adapter (claude-agent-acp): make it run the claude installed above, whose
# path the claude-code-oauth profile allows, instead of the copy bundled in its
# own node_modules.
ENV CLAUDE_CODE_EXECUTABLE=/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
COPY claude-start.json /etc/claude-start.json
COPY --chmod=755 claude-start claude-acp-start claude-acp-mkcwd-start /usr/local/bin/
COPY --chmod=644 claude-acp-mkcwd.js /usr/local/bin/claude-acp-mkcwd.js
