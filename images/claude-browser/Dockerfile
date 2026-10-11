# Claude Code sandbox image with a headless browser, for OpenShell.
#
#   podman build -t claude-sandbox:latest images/claude-sandbox    (or: make images)
#   podman build -t claude-browser:latest images/claude-browser
#
# Adds Playwright MCP (@playwright/mcp) and Playwright's headless Chromium to
# the claude-sandbox image, and registers the MCP server as `playwright` in
# Claude Code. The browser runs inside the sandbox, so OpenShell decides which
# hosts it may reach. Use it with policies/browser.yaml, which lists them.
FROM localhost/claude-sandbox:latest
# Browsers in a fixed path outside $HOME, so a network rule can name the
# Chromium binary (/opt/ms-playwright/**) and the agent can't replace it
# (/opt is read-only in the sandbox). certutil (libnss3-tools) is for the CA,
# see playwright-mcp-start.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npm install -g @playwright/mcp \
 && node /usr/local/lib/node_modules/@playwright/mcp/node_modules/playwright/cli.js \
      install --with-deps --only-shell chromium \
 && apt-get install -y --no-install-recommends libnss3-tools \
 && rm -rf /var/lib/apt/lists/*
# Playwright MCP config: headless, profile in memory only (no cookies or
# logins kept), and --no-zygote. OpenShell's syscall filter makes Chromium's
# zygote crash ("Target crashed"), even with Chromium's own sandbox off. The
# OpenShell sandbox is the boundary here.
COPY playwright-mcp.json /etc/playwright-mcp.json
# Adds the sandbox's OpenShell CA to Chromium, then starts the server.
COPY --chmod=755 playwright-mcp-start /usr/local/bin/
# Registers the server for Claude Code: claude-start copies this file to
# $HOME/.claude.json on first start.
COPY claude-start.json /etc/claude-start.json
# Tools Claude Code may not use, as managed settings (the agent can't change
# /etc). browser_run_code_unsafe runs any code in the MCP server's Node.js,
# browser_file_upload sends local files to a site. This is extra caution, not
# the boundary: the agent can run code with Bash anyway, and the network rules
# limit where anything can go.
COPY managed-settings.json /etc/claude-code/managed-settings.json
