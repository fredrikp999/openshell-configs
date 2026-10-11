---
name: openshell-setup
description: Set up NVIDIA OpenShell on this machine end to end - Podman, the OpenShell gateway, provider profiles and providers, agent images, and a first sandbox. Use when the user asks to set up, install, check or repair OpenShell, or to get Claude Code or OpenCode running in a sandbox.
---

# OpenShell setup

Follow the repo's README (chapters "Setup" and "Agents") and use the repo's scripts. Work in the repo root. Check what is already done before each step and skip it, so the skill can be run again safely.

## Rules
- Never read, print or `cat` `.env`, and never put a key or token on a command line. Providers are created by `./provider.sh`, which loads `.env` in a subshell.
- Ask the user before running the OpenShell installer (`curl ... | sh`), changing `~/.config/openshell/gateway.toml`, or restarting the gateway.
- If `claude setup-token` or a browser login is needed, ask the user to run it themselves (`! claude setup-token`) and put the result in `.env` (`cp .env.example .env`, `chmod 600 .env`).
- Ask which agent they want if it isn't clear: `claude` (Claude subscription) or `opencode` (OpenRouter). Do only that agent's steps.

## Steps
1. **Podman 5.x**: `podman --version`. If missing, follow README "Podman" for the OS (`uname`). macOS needs `podman machine init && podman machine start`. Verify with `podman run --rm quay.io/podman/hello`.
2. **OpenShell**: `openshell status`. If the command or gateway is missing, follow README "Install OpenShell", then set `compute_driver = "podman"` in `~/.config/openshell/gateway.toml`, run `openshell-gateway config preflight --path ~/.config/openshell/gateway.toml` and restart the gateway (`brew services restart openshell` on macOS, `systemctl --user restart openshell-gateway` on Linux). Re-check `openshell status`.
3. **Credentials**: make sure `.env` exists and is `chmod 600`. Check only that the needed variable name has a non-empty value, without showing it, e.g. `grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.' .env` (or `OPENROUTER_API_KEY`). If empty, tell the user what to add and wait.
4. **Provider**: `./provider.sh claude` or `./provider.sh opencode`. It imports the profile and creates the provider; it skips both when they exist.
5. **Image**: skip if `podman image exists claude-sandbox:latest` (or `opencode-sandbox:latest`) succeeds. Otherwise `podman build -t claude-sandbox:latest -f Dockerfile.claudecode .` (or `-t opencode-sandbox:latest -f Dockerfile.opencode`).
6. **Sandbox**: offer `./sandbox.sh <agent> [name]`, or `--vscode`. It is interactive, so give the user the command rather than running it, unless they ask to run a non-interactive check such as `./sandbox.sh claude test -- -p 'reply with OK'`.

## Finish
Report each step as done, skipped (already in place) or failed, with the failing command's output. On failure, look up the symptom in README "Troubleshooting" before guessing.
