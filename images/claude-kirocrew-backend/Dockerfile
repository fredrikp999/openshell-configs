# Claude Code as an ACP backend for an external Kiro Crew, on a Mac whose Kiro
# Crew workspace root cannot be created inside the sandbox at runtime (/Users
# does not exist there, and creating it needs write access to / -- which the
# sandbox's filesystem policy never grants). This bakes a symlink for it
# instead, at build time (root, no Landlock involved), into the sandbox's own
# writable home. See docs/extras.md#claude-code-as-an-acp-backend-for-an-external-kiro-crew.
#
# KIROCREW_WORKSPACE_ROOT is personal to this Mac and this user, not portable
# as-is: pass it as a build arg (default below is a placeholder that will not
# build without one). Find yours from the cwd Kiro Crew's error names, or
# `kirocrew config get agent.workspace_dir`.
#
#   podman build -t claude-kirocrew-backend:latest \
#     --build-arg KIROCREW_WORKSPACE_ROOT=/Users/you/dev/kirocrew \
#     images/claude-kirocrew-backend
#   # or: make claude-kirocrew-backend KIROCREW_WORKSPACE_ROOT=/Users/you/dev/kirocrew
FROM localhost/claude-sandbox:latest
ARG KIROCREW_WORKSPACE_ROOT
RUN test -n "$KIROCREW_WORKSPACE_ROOT" || { echo "KIROCREW_WORKSPACE_ROOT build arg is required (see this Dockerfile's header)" >&2; exit 1; } \
 && mkdir -p "$(dirname "$KIROCREW_WORKSPACE_ROOT")" \
 && ln -s /sandbox/kirocrew-workspace "$KIROCREW_WORKSPACE_ROOT"
