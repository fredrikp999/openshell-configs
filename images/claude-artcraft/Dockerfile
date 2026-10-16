# Claude Code sandbox image with the ArtCraft apps VectorCraft (vector art,
# https://getartcraft.com/apps/vectorcraft) and PhotoCraft (photo editing,
# https://getartcraft.com/apps/photocraft), for OpenShell.
#
#   make claude-artcraft           (builds claude-sandbox first)
#   podman build -t claude-artcraft:latest images/claude-artcraft
#
# Adds the headless vectorcraft-cli and photocraft-cli to the claude-sandbox
# image and registers their MCP servers as `vectorcraft` and `photocraft` in
# Claude Code, so Claude can draw SVG and PDF and edit photos. Both work on
# local files and need no network at run time; policies/artcraft.yaml is the
# terminal policy. The MCP servers may only read and write below /sandbox.
# The image also has the skills in skills/ (clean-vector-from-raster), copied to
# ~/.claude/skills on first start by artcraft-init.
FROM localhost/claude-sandbox:latest

ARG VECTORCRAFT_VERSION=0.12.0
ARG PHOTOCRAFT_VERSION=0.9.0

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

# Registers the servers for Claude Code: claude-start copies this file to
# $HOME/.claude.json on first start.
COPY claude-start.json /etc/claude-start.json

# Skills for Claude Code, copied to ~/.claude/skills on first start
# (artcraft-init). claude-start and claude-acp-start run it, then do what the
# base image's versions do.
COPY skills /opt/artcraft-skills
COPY --chmod=755 artcraft-init claude-start claude-acp-start /usr/local/bin/
