# Antigravity CLI (agy) sandbox image with HyperFrames and a browser, for OpenShell.
#
#   make agy-hyperframes        (builds claude-sandbox, claude-browser and claude-hyperframes first)
#   podman build -t agy-hyperframes:latest images/agy-hyperframes
#
# Builds on claude-hyperframes for its Node.js 22, headless Chromium with
# Playwright MCP, FFmpeg, fonts and the HyperFrames CLI (`npx hyperframes`
# finds the global install, so it needs no registry). Adds agy, installed like in images/agy-sandbox, and its
# community ACP adapter, and registers Playwright MCP with agy. Claude Code is
# still in the image but has no provider here.
# Use it with policies/agy-hyperframes.yaml (bin/sandbox.sh agy-hyperframes).
FROM localhost/claude-hyperframes:latest

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- --dir /usr/local/bin \
 && npm install -g google-antigravity-acp@2.0.1 \
 && rm -rf /root/.gemini /root/.cache /root/.config /root/.npm \
 && sed -i '/Antigravity CLI installer/,+1d' /root/.bashrc \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Like claude-start and claude-acp-start in claude-hyperframes: agy-init runs
# hyperframes-init (skills, OpenShell CA for Chromium) and registers the
# Playwright MCP server of claude-browser with agy (agy mcp add), then agy or
# the adapter starts.
COPY --chmod=755 agy-init agy-start agy-acp-start /usr/local/bin/
