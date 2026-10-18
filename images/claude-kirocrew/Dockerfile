# Claude Code sandbox image with Kiro Crew (https://kiro.dev), for OpenShell.
#
#   make claude-kirocrew           (builds claude-sandbox first)
#   podman build -t claude-kirocrew:latest images/claude-kirocrew
#
# Builds on claude-sandbox (Node 22, Claude Code, and the claude-agent-acp
# adapter) and adds Kiro Crew with Python 3.12. Kiro Crew uses Claude Code
# over the Agent Client Protocol (ACP) as its agent harness and serves a web
# dashboard on port 5476. Forward its port with `bin/sandbox.sh --forward 5476`
# or open http://127.0.0.1:5476 when running with `bin/sandbox.sh claude my-crew --kirocrew`.
FROM localhost/claude-sandbox:latest

# Runtime dependencies for Kiro Crew and Python 3.12
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl ca-certificates git ripgrep procps \
 && rm -rf /var/lib/apt/lists/*

# Install Kiro Crew with its managed Python 3.12 into /opt/kirocrew.
# The export applies to the installer subshell so artifacts land in /opt.
# At runtime KIROCREW_HOME is unset/defaults to $HOME/.kiro/crew (/sandbox/.kiro/crew).
RUN mkdir -p /opt/kirocrew \
 && export KIROCREW_HOME=/opt/kirocrew/crew \
           KIROCREW_VENV=/opt/kirocrew/venv \
           KIROCREW_PYTHON_DIR=/opt/kirocrew/python \
 && curl -fsSL https://download.crew.kiro.dev/cli.sh | sh \
 && chmod -R a+rX /opt/kirocrew \
 && ln -sf /opt/kirocrew/venv/bin/kirocrew /usr/local/bin/kirocrew \
 && ln -sf /opt/kirocrew/venv/bin/python3 /usr/local/bin/python3 \
 && ln -sf /opt/kirocrew/venv/bin/python /usr/local/bin/python

ENV KIROCREW_BIND=0.0.0.0 \
    KIROCREW_PORT=5476 \
    CLAUDE_AGENT_ACP_BIN=/usr/local/bin/claude-agent-acp

# Default configuration template (ACP backend set to Claude Code)
COPY config.json /etc/kirocrew/config.json

# Skip Claude Code onboarding on first start
COPY claude-start.json /etc/claude-start.json

# Entrypoint wrappers and startup scripts
COPY --chmod=755 kirocrew-init kirocrew-start claude-start claude-acp-start /usr/local/bin/

# Expose Kiro Crew web interface port
EXPOSE 5476
