# Agents
Both agent chapters follow the same steps: profile, provider, image, sandbox.

## Claude Code with a Claude subscription
Claude Code runs with a Claude subscription (Pro/Max) via an OAuth token, not an API key. The upstream [claude-code.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/claude-code.yaml) profile only supports API keys, so this repo has its own profile: [providers/claude-code-oauth.yaml](../providers/claude-code-oauth.yaml). It injects the token as `Authorization: Bearer` only on requests to the endpoints listed in the profile (`api.anthropic.com` and `platform.claude.com`), so the real token never lives inside the sandbox.

### Create an OAuth token (on the host)
Run on your own machine. It opens the browser to log in with your Claude account and prints a long-lived (1 year) token:
```bash
claude setup-token
```
* Store the token in the Keychain (it prompts for the value), or see [Credentials](setup.md#credentials) for `.env` and other secrets managers:
```bash
security add-generic-password -U -s openshell -a CLAUDE_CODE_OAUTH_TOKEN -w
```

### Import the profile
(Skip this and the next section with `bin/provider.sh claude`, which imports the profile and creates the provider.)
```bash
openshell provider profile lint   -f providers/claude-code-oauth.yaml
openshell provider profile import -f providers/claude-code-oauth.yaml
```
* After editing the file later, use `update` instead of `import`. See [Update a profile](customizing.md#update-a-profile).

### Create the provider
The profile is only a template. The provider is the instance that holds your token in the gateway, and it is what a sandbox refers to with `--provider`. Importing the profile does not create the provider.

* Check that the profile is imported; `claude-code-oauth` should be listed:
```bash
openshell provider profile list
```

* Create the provider. `--from-existing` reads the token from the `CLAUDE_CODE_OAUTH_TOKEN` environment variable, so set it for this one command only (see [Credentials](setup.md#credentials)):
  * `--name` is your own name for the provider, used later with `--provider claude`
  * `--type` is the `id` of the profile in [providers/claude-code-oauth.yaml](../providers/claude-code-oauth.yaml)
```bash
(export CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s openshell -a CLAUDE_CODE_OAUTH_TOKEN -w)"
 openshell provider create \
  --name claude \
  --type claude-code-oauth \
  --from-existing)
```
Expected output: `✓ Created provider claude`

* Verify; `claude` should be listed with type `claude-code-oauth` and 1 credential key:
```bash
openshell provider list
```
```
NAME        TYPE               CREDENTIAL_KEYS   CONFIG_KEYS
claude      claude-code-oauth  1                 0
```

### Build the image
There is no ready-made image, so build one from [images/claude-sandbox](../images/claude-sandbox/Dockerfile). It is `node:22-slim` with `git`, Claude Code and the ACP adapter `claude-agent-acp` (both installed via npm), plus two wrappers from the same folder that skip Claude Code's first-run onboarding: `claude-start` then starts `claude`, and `claude-acp-start` starts `claude-agent-acp` (for [ACP](extras.md#acp-agent-client-protocol)).
```bash
podman build -t claude-sandbox:latest images/claude-sandbox
```
Or the same with `make claude-sandbox`.

Why the wrappers are needed: onboarding runs a connectivity check that connects to `api.anthropic.com` without going through the OpenShell proxy. The sandbox denies that connection, and Claude Code exits with `Failed to connect to api.anthropic.com: EACCES`. On first start, the wrappers copy `/etc/claude-start.json`, which holds `{"hasCompletedOnboarding": true}`, to `~/.claude.json` (`/sandbox/.claude.json`), so the check is skipped. (The [browser image](extras.md#headless-browser-use) replaces that file to also register its MCP server.) All other traffic goes through the proxy and works.

### Create the sandbox
Quickest: `bin/sandbox.sh claude [name]` for Claude in your terminal, or add `--vscode` for VS Code. See [Start a sandbox](working-in-sandboxes.md#start-and-use-a-sandbox). The sections below show what it does by hand.

Always start Claude with `claude-start`, not `claude`.

#### With VS Code and a terminal (recommended)
The sandbox runs `sleep infinity` as its main process, so it keeps running while you start and quit Claude. The [terminal policy](customizing.md#filesystem-policy) lets VS Code open terminals inside it.
```bash
openshell sandbox create \
  --name claude-agent1 \
  --from claude-sandbox:latest \
  --provider claude \
  --policy policies/vscode-terminal.yaml \
  --detach \
  -- sleep infinity

openshell sandbox connect claude-agent1 --editor vscode
```
Then start Claude in one of these ways:
* **In VS Code's terminal** (*Terminal > New Terminal*), which runs inside the sandbox:
```bash
cd /sandbox/myrepo
claude-start
```
* **From a terminal on your machine:**
```bash
openshell sandbox exec claude-agent1 --tty --workdir /sandbox/myrepo -- claude-start
```
* You can run several Claude sessions in the same sandbox, e.g. one per terminal tab.

#### Claude as the main process
Simpler, but the sandbox stops (`Completed`) when you quit Claude, and VS Code can no longer connect.
```bash
openshell sandbox create \
  --name claude-agent1 \
  --from claude-sandbox:latest \
  --provider claude \
  --policy policies/vscode-terminal.yaml \
  -- claude-start
```
* Arguments are passed on to `claude`, e.g. `-- claude-start --model sonnet`
* Smoke test (non-interactive): replace `-- claude-start` with `-- claude-start -p 'reply with OK'`

### Things to watch for
* **Binary paths** - only the binaries listed in the profile may reach the endpoints and get the token. The profile covers `/usr/bin/claude`, `/usr/local/bin/claude` and the npm install path `/usr/local/lib/node_modules/@anthropic-ai/**`. If requests are denied, check `openshell logs claude-agent1` for the blocked binary path, add it to `binaries` and [update the profile](customizing.md#update-a-profile).
* **Don't use `/login` inside the sandbox** - an interactive login would store the OAuth credentials in the sandbox (`~/.claude/.credentials.json`) and needs extra login hosts opened. `setup-token` + provider keeps the token outside.
* **Token expiry** - the token is valid for a year. Regenerate with `claude setup-token`, store the new token (`security add-generic-password -U ...` replaces the old one), and update the provider:
```bash
bin/provider.sh --update claude
```
  To be reminded before it expires, set the expiry on the provider, see [Token expiry](setup.md#token-expiry).
* **Only Anthropic hosts in the profile** - OpenShell swaps the token placeholder for the real token on requests to *every* host in the profile. Shared third-party services such as `sentry.io` would let a manipulated agent send the token, or your code, to someone else's account, so the profile lists only `api.anthropic.com` and `platform.claude.com`. The image sets `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, so Claude Code doesn't try to send telemetry, error reports or update checks (`statsig.anthropic.com`, `sentry.io`, Datadog).
* **The Claude Code VS Code extension** would run its own bundled `claude` binary from `~/.vscode-server/extensions/...`, which isn't in the profile's `binaries` list, so its requests will most likely be denied (not tested). Use the CLI in the terminal instead.

## OpenCode with OpenRouter
OpenCode uses models through the OpenRouter API, with an OpenRouter API key.

### Import the profile
(Skip this and the next section with `bin/provider.sh opencode`, which imports the profile and creates the provider.)

The profile describes the OpenRouter API, not OpenCode: the API key, the host `openrouter.ai`, and which binary may use the key. This repo has a local copy of the upstream profile: [providers/openrouter.yaml](../providers/openrouter.yaml). It doesn't change with upstream, and only `/usr/local/bin/opencode` may use the key, the opencode path in the image.
```bash
openshell provider profile lint   -f providers/openrouter.yaml
openshell provider profile import -f providers/openrouter.yaml
```
* After editing the file later, use `update` instead of `import`. See [Update a profile](customizing.md#update-a-profile).
* To use the upstream version directly instead: `openshell provider profile import --url https://raw.githubusercontent.com/NVIDIA/OpenShell/main/providers/openrouter.yaml`

### Create the provider
* Store the key in the Keychain (it prompts for the value; see [Credentials](setup.md#credentials) for `.env` and other secrets managers) and create the provider:
```bash
security add-generic-password -U -s openshell -a OPENROUTER_API_KEY -w
(export OPENROUTER_API_KEY="$(security find-generic-password -s openshell -a OPENROUTER_API_KEY -w)"
 openshell provider create \
  --name openrouter \
  --type openrouter \
  --from-existing)
```
* Verify with `openshell provider list`.

### Build the image
The official image `ghcr.io/anomalyco/opencode:latest` is Alpine-based and has no `git` or `bash`, and its entrypoint is `opencode`. [images/opencode-sandbox](../images/opencode-sandbox/Dockerfile) builds on it:
* adds `git` (for [getting code in and out](working-in-sandboxes.md#getting-code-in-and-out)), `bash` (VS Code's terminal), `libstdc++` (needed by VS Code Server on Alpine) and `script`
* clears the entrypoint, so the command after `--` (e.g. `sleep infinity`) runs as is
* keeps `opencode` at `/usr/local/bin/opencode`, the only path the `openrouter` profile lets use the API key
```bash
podman build -t opencode-sandbox:latest images/opencode-sandbox
```
Or the same with `make opencode-sandbox`.

### Create the sandbox
Quickest: `bin/sandbox.sh opencode [name]` for OpenCode in your terminal, or add `--vscode` for VS Code. See [Start a sandbox](working-in-sandboxes.md#start-and-use-a-sandbox). The sections below show what it does by hand.

#### With VS Code and a terminal (recommended)
```bash
openshell sandbox create \
  --name opencode-agent2 \
  --from opencode-sandbox:latest \
  --provider openrouter \
  --policy policies/vscode-terminal.yaml \
  --detach \
  -- sleep infinity

openshell sandbox connect opencode-agent2 --editor vscode
```
Then start OpenCode in one of these ways:
* **In VS Code's terminal** (*Terminal > New Terminal*):
```bash
cd /sandbox/myrepo
opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```
* **From a terminal on your machine:**
```bash
openshell sandbox exec opencode-agent2 --tty --workdir /sandbox -- opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```

#### OpenCode as the main process
Uses the official image directly. The sandbox stops when you quit OpenCode, and the image doesn't support VS Code's terminal.
```bash
openshell sandbox create \
  --name opencode-agent1 \
  --from ghcr.io/anomalyco/opencode:latest \
  --provider openrouter \
  -- opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```

### Things to watch for
* **Only the chat endpoint** - the profile allows just `POST /api/v1/chat/completions` on openrouter.ai, the one call OpenCode makes. Other OpenRouter API paths (keys, credits, account) are denied. Check with `openshell logs <sandbox>` if a new OpenCode version needs more.
* **An agent can bring its own key** - OpenShell only swaps its placeholder for your key; an `Authorization` header the agent sets itself goes through unchanged (tested: a made-up key reached OpenRouter and was rejected there). A manipulated agent could therefore send your code in a chat request on someone else's OpenRouter account, which can log prompts. The path rule above narrows this but can't close it. Keep secrets out of sandboxes, and treat what's in a sandbox as visible to the model provider anyway.
* **Binary path** - only `/usr/local/bin/opencode` may use the key. If you install OpenCode elsewhere (e.g. via npm), add that path to the profile and [update it](customizing.md#update-a-profile).
* **Hosts left blocked** - OpenCode tries `models.opencode.ai` (model list) and `registry.npmjs.org` (update check). Both are denied. OpenCode works without them, so leave them blocked unless you need them.
* **The sandbox user** is uid 1000 with `HOME=/sandbox`.
