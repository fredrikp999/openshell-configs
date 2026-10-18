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

# Kiro Crew pins every path by opening / and then each component. OpenShell's Landlock
# baseline never grants / itself, so that open fails with EACCES and app backends, project
# skills and the pycache sweep break. Start the walk at the first readable component instead.
# The script fails the build if Kiro Crew changes the code it patches. Remove it once Kiro
# Crew or OpenShell fixes this upstream.
COPY patch-unreadable-root.py /tmp/patch-unreadable-root.py
RUN python3 /tmp/patch-unreadable-root.py /opt/kirocrew/venv/lib/python3.12/site-packages/kiro_crew \
 && rm /tmp/patch-unreadable-root.py

# Kiro Crew runs git, pip and npm (app installs) with a scrubbed environment: no
# GIT_SSL_CAINFO, SSL_CERT_FILE, PIP_CERT or NODE_EXTRA_CA_CERTS, and no user or global
# config. OpenShell's proxy terminates TLS with its own CA, so those tools then fail with
# "server certificate verification failed" or "self-signed certificate in certificate
# chain". At sandbox start the supervisor writes a bundle (system CAs plus the proxy CA)
# at the path below. Point the system-wide trust files and tool configs at it. Outside
# OpenShell the links dangle and TLS fails closed.
#   git (GnuTLS) and OpenSSL clients: /etc/ssl/certs/ca-certificates.crt, /etc/ssl/cert.pem
#   pip: /etc/pip.conf     npm: /usr/local/etc/npmrc
RUN CA=/run/openshell-supervisor-ca/material/ca-bundle.crt \
 && ln -sf "$CA" /etc/ssl/certs/ca-certificates.crt \
 && ln -sf "$CA" /etc/ssl/cert.pem \
 && printf '[global]\ncert = %s\n' "$CA" > /etc/pip.conf \
 && mkdir -p /usr/local/etc \
 && printf 'cafile=%s\n' "$CA" > /usr/local/etc/npmrc

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
