# Claude Code sandbox image with the ArtCraft apps VectorCraft (vector art,
# https://getartcraft.com/apps/vectorcraft) and PhotoCraft (photo editing,
# https://getartcraft.com/apps/photocraft), for OpenShell.
#
#   make claude-graphics           (builds claude-sandbox first)
#   podman build -t claude-graphics:latest images/claude-graphics
#
# Adds the headless vectorcraft-cli and photocraft-cli to the claude-sandbox
# image and registers their MCP servers as `vectorcraft` and `photocraft` in
# Claude Code, so Claude can draw SVG and PDF and edit photos. Both work on
# local files and need no network at run time; policies/graphics.yaml is the
# terminal policy plus read-only access to PyPI. The MCP servers may only read and write below /sandbox.
# The image also has the skills in skills/ (clean-vector-from-raster), copied to
# ~/.claude/skills on first start by graphics-init, Python 3, and
# graphics-gallery, a web page for browsing the images (forward its port with
# bin/sandbox.sh --forward PORT).
FROM localhost/claude-sandbox:latest

# Python 3 from Debian with pip and venv (Debian's pip refuses system-wide
# installs: use `uv venv` or `python3 -m venv .venv`), for scripts and for
# graphics-gallery. policies/graphics.yaml lets python3 and uv reach PyPI.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
 && rm -rf /var/lib/apt/lists/*

ARG UV_VERSION=0.13.1
ARG VECTORCRAFT_VERSION=0.12.0
ARG PHOTOCRAFT_VERSION=0.9.0
ARG REPLICATE_MCP_VERSION=0.9.0

# Install wheels only: a source distribution runs the package's build code at
# install time. pip reads PIP_ONLY_BINARY; uv reads /etc/uv/uv.toml (its
# UV_NO_BUILD variable doesn't apply to `uv pip`). `PIP_ONLY_BINARY= pip ...` and
# `uv --no-config ...` turn it off for one command.
ENV PIP_ONLY_BINARY=:all:
COPY uv.toml /etc/uv/uv.toml

# uv (https://docs.astral.sh/uv/), the release binary for this architecture,
# checked against its .sha256 file. It uses the Debian python3 above and never
# downloads a Python of its own (UV_PYTHON_DOWNLOADS=never), since the policy
# only allows PyPI.
ENV UV_PYTHON_DOWNLOADS=never
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && case "$(uname -m)" in aarch64) a=aarch64 ;; x86_64) a=x86_64 ;; *) echo "unsupported: $(uname -m)" >&2; exit 1 ;; esac \
 && n=uv-$a-unknown-linux-gnu \
 && cd /tmp \
 && curl -fsSLO "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/$n.tar.gz" \
 && curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/$n.tar.gz.sha256" | sed 's/ .*/  '"$n"'.tar.gz/' | sha256sum -c - \
 && tar xzf "$n.tar.gz" \
 && install -m 755 "$n/uv" "$n/uvx" /usr/local/bin/ \
 && rm -rf "/tmp/$n" "/tmp/$n.tar.gz" \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Each app's release tarball for this machine's architecture, checked against
# the release's SHA256SUMS. Only the CLI is kept (the GUI needs a display).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && case "$(uname -m)" in aarch64) a=aarch64 ;; x86_64) a=x86_64 ;; *) echo "unsupported: $(uname -m)" >&2; exit 1 ;; esac \
 && cd /tmp \
 && for app in vectorcraft:${VECTORCRAFT_VERSION} photocraft:${PHOTOCRAFT_VERSION}; do \
      p=${app%%:*}; v=${app##*:}; \
      n=$p-$v-linux-$a; \
      u=https://github.com/storytold/$p/releases/download/v$v; \
      curl -fsSLO "$u/$n.tar.gz" \
   && curl -fsSL "$u/SHA256SUMS.txt" | grep " $n.tar.gz\$" | sha256sum -c - \
   && tar xzf "$n.tar.gz" "$n/bin/$p-cli" "$n/share/doc/$p" \
   && install -m 755 "$n/bin/$p-cli" /usr/local/bin/$p-cli \
   && mkdir -p /usr/local/share/doc/$p \
   && cp -r "$n/share/doc/$p/." /usr/local/share/doc/$p/ \
   && rm -rf "/tmp/$n" "/tmp/$n.tar.gz" \
   || exit 1; \
    done \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Replicate's MCP server (stdio), registered by graphics-init only when the
# replicate provider is attached. The hosted server (mcp.replicate.com) wants an
# OAuth token and rejects an API token, so this local one is used; it calls
# api.replicate.com with REPLICATE_API_TOKEN (command: mcp-server).
RUN npm install -g "replicate-mcp@${REPLICATE_MCP_VERSION}" && npm cache clean --force

# Permissions for Claude Code: what is allowed without asking, what asks, what
# is denied. Managed settings (/etc/claude-code), which the agent can't change;
# your own rules in ~/.claude/settings.json add to them but can't lift a deny.
COPY managed-settings.json /etc/claude-code/managed-settings.json

# Registers the servers for Claude Code: claude-start copies this file to
# $HOME/.claude.json on first start.
COPY claude-start.json /etc/claude-start.json

# Skills for Claude Code, copied to ~/.claude/skills on first start
# (graphics-init). claude-start and claude-acp-start run it, then do what the
# base image's versions do.
COPY skills /usr/local/share/graphics-skills
# graphics-key: chroma-key cleanup of PNGs and traced SVGs for the
# clean-vector-from-raster workflow (graphics-key --help). It uses numpy and
# Pillow when the agent installs them, else its own PNG code.
COPY --chmod=755 graphics-init graphics-gallery graphics-key claude-start claude-acp-start /usr/local/bin/
