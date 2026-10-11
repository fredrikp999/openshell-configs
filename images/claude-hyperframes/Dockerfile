# Claude Code sandbox image for HyperFrames (https://hyperframes.heygen.com):
# videos made from HTML, rendered with headless Chrome, for OpenShell.
#
#   make claude-hyperframes        (builds claude-sandbox and claude-browser first)
#   podman build -t claude-hyperframes:latest images/claude-hyperframes
#
# Builds on claude-browser (Playwright MCP and headless Chromium, so Claude can
# look at what it builds) and adds the HyperFrames CLI, FFmpeg, fonts and the
# HyperFrames skills. Use it with policies/hyperframes.yaml, which allows the
# CDNs that compositions load from, and watch the preview from your browser
# with `openshell forward` (bin/sandbox.sh --hyperframes --forward PORT).
FROM localhost/claude-browser:latest

ARG HYPERFRAMES_VERSION=0.8.147

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg unzip fonts-liberation fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g hyperframes@${HYPERFRAMES_VERSION}
# OpenShell's syscall filter doesn't allow changing process priority, and the
# HyperFrames render/lint worker lowers its own priority without catching the
# error, so every render fails with "uv_os_setpriority returned EPERM". Make
# that call best-effort. The grep fails the build if a new version changes the
# code, so the patch gets checked (and dropped once fixed upstream).
RUN f=/usr/local/lib/node_modules/hyperframes/dist/renderSetupWorker.js \
 && grep -q '^    setPriority(constants.priority.PRIORITY_LOW);$' "$f" \
 && sed -i 's/^    setPriority(constants.priority.PRIORITY_LOW);$/    try { setPriority(constants.priority.PRIORITY_LOW); } catch {}/' "$f"

# The HyperFrames skills of the same release, copied to ~/.claude/skills on
# first start (hyperframes-init).
RUN git clone -q --depth 1 --branch v${HYPERFRAMES_VERSION} \
      https://github.com/heygen-com/hyperframes /tmp/hf \
 && mkdir -p /opt/hyperframes-skills \
 && for d in /tmp/hf/skills/*/; do cp -r "$d" /opt/hyperframes-skills/; done \
 && rm -rf /tmp/hf

# HyperFrames renders with the headless Chromium from claude-browser (it can't
# download its own in the sandbox). No telemetry, update checks or skill
# downloads on `init` (the skills are preinstalled), and container-friendly
# rendering.
RUN ln -s "$(ls -d /opt/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell | head -n1)" \
      /usr/local/bin/chrome-headless-shell
ENV HYPERFRAMES_BROWSER_PATH=/usr/local/bin/chrome-headless-shell \
    HYPERFRAMES_NO_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    HYPERFRAMES_NO_UPDATE_CHECK=1 \
    HYPERFRAMES_SKIP_SKILLS=1 \
    PRODUCER_LOW_MEMORY_MODE=true

# hyperframes-init: skills and the OpenShell CA for Chromium. claude-start and
# claude-acp-start run it, then do what the base image's versions do.
COPY --chmod=755 hyperframes-init claude-start claude-acp-start /usr/local/bin/
