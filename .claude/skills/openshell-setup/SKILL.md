---
name: openshell-setup
description: Set up NVIDIA OpenShell on this machine end to end - Podman, the OpenShell gateway, provider profiles and providers, agent images, and a first sandbox. Use when the user asks to set up, install, check or repair OpenShell, or to get Claude Code or OpenCode running in a sandbox.
---

# OpenShell setup

Follow the repo's docs (`docs/setup.md` and `docs/agents.md`) and use the repo's scripts. Work in the repo root. Check what is already done before each step and skip it, so the skill can be run again safely.

## Rules
- Never read, print or `cat` `.env`, never run `security find-generic-password` with `-w`, and never put a key or token on a command line. Providers are created by `bin/provider.sh`, which reads the key itself (environment, then Keychain, then `.env`).
- Ask the user before running the OpenShell installer (`curl ... | sh`), changing `~/.config/openshell/gateway.toml`, or restarting the gateway.
- If `claude setup-token` or a browser login is needed, ask the user to run it themselves (`! claude setup-token`) and store the result in the Keychain themselves (`! security add-generic-password -U -s openshell -a CLAUDE_CODE_OAUTH_TOKEN -w`, which prompts for it). Only suggest `.env` if they're not on macOS or ask for it.
- Ask which agent they want if it isn't clear: `claude` (Claude subscription) or `opencode` (OpenRouter). Do only that agent's steps.

## Steps
1. **Podman 5.x**: `podman --version`. If missing, follow "Podman" in `docs/setup.md` for the OS (`uname`). macOS needs `podman machine init && podman machine start`. Verify with `podman run --rm quay.io/podman/hello`.
2. **OpenShell**: `openshell status`. If the command or gateway is missing, follow "Install OpenShell" in `docs/setup.md`, then set `compute_driver = "podman"` in `~/.config/openshell/gateway.toml`, run `openshell-gateway config preflight --path ~/.config/openshell/gateway.toml` and restart the gateway (`brew services restart openshell` on macOS, `systemctl --user restart openshell-gateway` on Linux). Re-check `openshell status`.
3. **Credentials**: skip if the provider already exists (`openshell provider list`). Otherwise check, without showing the value, that the key is in the Keychain: `security find-generic-password -s openshell -a CLAUDE_CODE_OAUTH_TOKEN >/dev/null` (or `OPENROUTER_API_KEY`), or else in `.env`: `grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.' .env`. If neither has it, tell the user how to store it (see Rules) and wait.
4. **Provider**: `bin/provider.sh claude` or `bin/provider.sh opencode`. It imports the profile and creates the provider; it skips both when they exist. For a new token: `bin/provider.sh --update claude`.
5. **Image**: skip if `podman image exists claude-sandbox:latest` (or `opencode-sandbox:latest`) succeeds. Otherwise `make claude-sandbox` (or `make opencode-sandbox`), which runs `podman build` on the image's folder in `images/`.
6. **Sandbox**: offer `bin/sandbox.sh <agent> [name]`, or `--vscode`. It is interactive, so give the user the command rather than running it, unless they ask to run a non-interactive check such as `bin/sandbox.sh claude test -- -p 'reply with OK'`.

## Finish
Report each step as done, skipped (already in place) or failed, with the failing command's output. On failure, look up the symptom in `docs/troubleshooting.md` before guessing.
