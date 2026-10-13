# Agents
The agent chapters follow the same steps: profile, provider, image, sandbox. Antigravity CLI is the exception: it has no provider, and you log in inside the sandbox. The next section explains the difference.

## Two ways to sign in: provider or login in the sandbox
The agents here use one of two ways to get at your account. Which one an agent can use depends on the agent, not on a choice in this repo.

**Credential in a provider** (Claude Code, OpenCode). You create the credential on the host (`claude setup-token`, an OpenRouter API key) and store it in a provider in the gateway. The sandbox only gets a placeholder in an environment variable, e.g. `CLAUDE_CODE_OAUTH_TOKEN=openshell:resolve:env:...`. When the agent sends a request with the placeholder to a host in the profile, OpenShell's proxy swaps in the real value on the way out. The profile also says which binaries may do that.

**Login in the sandbox** (Antigravity CLI). The agent runs its own OAuth login inside the sandbox and keeps the tokens there, like it would on your Mac. There's no provider; a sandbox policy ([policies/antigravity.yaml](../policies/antigravity.yaml)) opens the Google hosts it needs.

| | Provider (Claude Code, OpenCode) | Login in the sandbox (Antigravity CLI) |
|---|---|---|
| Where the secret is | In the gateway. The sandbox has a placeholder that's useless anywhere else | In the sandbox (`/sandbox`), including a long-lived refresh token |
| What the agent can do with it | Use it through the proxy, only on the hosts in the profile and only from the listed binaries | Read it, and send it anywhere the sandbox can reach |
| If the sandbox is compromised | The token can't be taken out; nothing to rotate | Assume the token is taken: log out, delete the sandbox, revoke the login in your Google account |
| Network access | From the provider's profile | From the sandbox policy, which you have to keep narrow |
| Setup | Once, on the host: create the token or key, `bin/provider.sh` | Once per sandbox: open the login link, paste the code back |
| New sandboxes | Get the provider with `--provider`, no login | Need a new login each |
| Token expiry and refresh | You renew it (Claude's token lasts a year, `bin/provider.sh --update`) | `agy` refreshes it itself, through `oauth2.googleapis.com` |
| Several agents, one account | One provider for any number of sandboxes | One login per sandbox, each revocable on its own |
| Depends on | The agent accepting a token from the environment (or a header the proxy can fill in) | Nothing beyond the agent's normal login |

**Why Antigravity CLI uses a login in the sandbox:** it has no way to take a token from the environment or a file you hand it; it only uses its own login, stored in its own token storage. A provider would work only with workarounds: a fake Google metadata server in the sandbox that hands `agy` the placeholder (`agy` accepts this with `AGY_ADC_AUTH=1`, tested), and a gateway refresh that needs `agy`'s OAuth client secret taken out of its binary plus your refresh token taken out of the macOS Keychain. That depends on undocumented internals that an update can break, so this repo doesn't do it. Gemini CLI, which does accept a token from the environment, is no option either: Google refuses Google-account logins from it ("This client is no longer supported for Gemini Code Assist for individuals") and points to Antigravity.

**What that means in practice:** treat an Antigravity sandbox as holding a live key to your Google account (with the `cloud-platform` scope). Don't widen its policy for other tasks; use a Claude Code or OpenCode sandbox for work that needs more network access, such as the [browser](extras.md#headless-browser-use) or package registries.

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
* **A more capable sandbox: `agy-hyperframes`** - `make agy-hyperframes`, then `bin/sandbox.sh agy my-video --hyperframes --forward 3102`. The image is built on [claude-hyperframes](extras.md#hyperframes) and adds `agy`, the ACP adapter and Python 3 (from Debian; no pip, because PyPI isn't allowed). `npx hyperframes` renders with headless Chromium and FFmpeg as there, and Playwright MCP is registered with `agy` (`agy mcp add playwright playwright-mcp-start`, done on first start by `agy-init`) so it can open and screenshot pages. Unlike the Claude image, nothing here blocks Playwright's `browser_run_code_unsafe` and `browser_file_upload` tools (that's Claude Code managed settings); the network rules are the limit. Pages other than the CDNs need a `browser_sites`-style rule in the policy. [policies/agy-hyperframes.yaml](../policies/agy-hyperframes.yaml) is the `agy` policy plus the CDN, font and registry rules of the HyperFrames policy. That makes it the less safe choice: `node` and Chromium, which can read the tokens, may now reach those hosts (read-only, but a GET can carry data in its URL). Use it only for that work, log in, and run `/logout` and delete the sandbox afterwards. The HyperFrames skills are copied to `~/.claude/skills` as in the Claude image, where `agy` doesn't look for them; `npx hyperframes docs` has the CLI's own docs. Log in once, as above; `--acp` works too.
* **The sandbox user** is uid 1000 with `HOME=/sandbox`.

## Antigravity CLI with a Google account
[Antigravity CLI](https://antigravity.google/docs/cli) (`agy`) is Google's coding agent. It uses your Google account and its subscription (e.g. Google AI Pro/Ultra).

Unlike the other agents, there is no provider: you log in **inside the sandbox**, and `agy` keeps its OAuth tokens there. See [Two ways to sign in](#two-ways-to-sign-in-provider-or-login-in-the-sandbox) for how that compares, and [Things to watch for](#things-to-watch-for-2) for what to do about it. Tested with a Google AI subscription: `agy` 1.3.3 in the sandbox signs in, shows the subscription's models and answers prompts.

### Build the image
[images/agy-sandbox](../images/agy-sandbox/Dockerfile) is `debian:bookworm-slim` with `git`, `ripgrep` and `agy` at `/usr/local/bin/agy`, installed with Google's install script (which checks the download against the release manifest's SHA-512).
```bash
podman build -t agy-sandbox:latest images/agy-sandbox
```
Or the same with `make agy-sandbox`.

### The policy
Without a provider, the network access comes from [policies/antigravity.yaml](../policies/antigravity.yaml): the terminal policy plus, for the `agy` binary only:
* `POST /token` on `oauth2.googleapis.com`, to exchange the login code for tokens and to refresh the access token
* `GET /oauth2/v2/userinfo` on `www.googleapis.com` and `GET /a/**` on `lh3.googleusercontent.com`, `agy`'s eligibility check (your account's email, name and profile picture)
* `POST /v1internal:*` and `GET /v1internal/**` on `daily-cloudcode-pa.googleapis.com`, the Code Assist API `agy` uses for everything else

Change it on a running sandbox with `openshell policy set <sandbox> --policy policies/antigravity.yaml --wait`.

### Create the sandbox and log in
```bash
bin/sandbox.sh agy my-task
```
This creates the sandbox with the image and policy above (no `--provider`) and starts `agy`. By hand:
```bash
openshell sandbox create \
  --name agy-agent1 \
  --from agy-sandbox:latest \
  --policy policies/antigravity.yaml \
  --detach \
  -- sleep infinity

openshell sandbox exec agy-agent1 --tty --workdir /sandbox -- agy
```
On first start, `agy` prints a login URL (it can't open a browser in the sandbox):
1. Open the URL in your browser on the Mac and sign in with your Google account.
2. The browser ends up on `antigravity.google` with an authorization code. Copy it.
3. Paste it into the "authorization code" field under the link in the terminal and press Enter. The login screen is about 26 lines high: in a smaller window the field is out of sight, so make the window taller or scroll down with Shift+↓.

The login stays in the sandbox (`/sandbox`), so you only do this once per sandbox. Non-interactive runs (`bin/sandbox.sh agy my-task -- -p 'reply with OK'`) only work after that; before it, they stop with "authentication required".

### Things to watch for
* **The tokens are in the sandbox** - including the long-lived refresh token, readable by the agent and by anything else running there. The policy limits where they could be sent to the four Google hosts above. Every rule you add to such a sandbox (another site, a package registry, a [browser](extras.md#headless-browser-use)) is another place they could go, so keep `agy` sandboxes to that policy. When you're done, run `/logout` in `agy` and delete the sandbox. To revoke the login entirely, remove Antigravity under [Third-party access](https://myaccount.google.com/connections) in your Google account.
* **Hosts left blocked** - `agy` also tries `play.googleapis.com` (usage logs), `antigravity-unleash.goog` (feature flags) and `www.gstatic.com`. They are denied, and `agy` works without them. If a new version needs more, check `openshell logs <sandbox> | grep DENIED` (or [bin/watch-denied.sh](../bin/watch-denied.sh)) and add it to the policy.
* **No self-update** - `agy` normally updates itself; in the sandbox `/usr` is read-only and the update host isn't allowed, so it skips that. Get a newer version with `make update`, then create a new sandbox (and log in again).
* **ACP through a community adapter** - `agy` has no Agent Client Protocol mode of its own. The image has [`google-antigravity-acp`](https://github.com/sibbl/google-antigravity-acp) (pinned, MIT, small and not from Google), which drives `agy`'s `stream-json` print mode and speaks ACP, so `bin/sandbox.sh agy my-task --acp` and `bin/acp_client.py` work once you have logged in. The adapter makes `agy` auto-approve tool permissions; set `AGY_ACP_ASK=1` in the command to pass `--no-skip-permissions`. See [ACP](extras.md#acp-agent-client-protocol). Google may not like third-party tools driving `agy` with a subscription login, so use it knowingly.
* **The sandbox user** is uid 1000 with `HOME=/sandbox`; `agy` keeps its settings and conversations in `/sandbox/.gemini/antigravity-cli`.
