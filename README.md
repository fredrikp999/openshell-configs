# OpenShell configs
Configs and notes for running AI coding agents (Claude Code, OpenCode) in [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandboxes with Podman, editing their files in VS Code, and moving code in and out.

| File | What it is |
|---|---|
| [providers/claude-code-oauth.yaml](providers/claude-code-oauth.yaml) | Profile for Claude Code with a Claude subscription (OAuth token) |
| [providers/openrouter.yaml](providers/openrouter.yaml) | Profile for the OpenRouter API, used by OpenCode |
| [policies/vscode-terminal.yaml](policies/vscode-terminal.yaml) | Sandbox policy: the default plus terminal access, for VS Code |
| [policies/example.yaml](policies/example.yaml) | Example sandbox policy with network rules, to copy and adapt |
| [Dockerfile.claudecode](Dockerfile.claudecode) | Image `claude-sandbox`: Claude Code, git and the `claude-start` wrapper |
| [Dockerfile.opencode](Dockerfile.opencode) | Image `opencode-sandbox`: the official OpenCode image plus git, bash and VS Code support |
| [sandbox.sh](sandbox.sh) | Starts an agent sandbox, in the terminal or in VS Code |
| [bundle.sh](bundle.sh) | Moves a git repo into a sandbox and the agent's commits back out, with git bundles |
| [.env.example](.env.example) | Template for `.env`, which holds your API key and token (ignored by git) |

## TL;DR
OpenShell runs AI coding agents in locked-down sandboxes. Agents get only the network access and credentials you allow, and API keys and tokens never enter the sandbox.

### Concepts
* **Gateway** - the local OpenShell server (`https://localhost:17670`) that manages everything below. It runs as a background service and starts sandboxes through a container runtime (here Podman).
* **Profile** - a template for a type of provider: which credential it needs (e.g. `CLAUDE_CODE_OAUTH_TOKEN`), which hosts it may reach, and which binaries may use it. A YAML file in [providers/](providers/), imported into the gateway. See [Provider profiles](#provider-profiles).
* **Provider** - an instance of a profile that holds your actual key or token, stored in the gateway. OpenShell's network proxy adds the credential to outgoing requests to the allowed hosts, so the agent never sees it.
* **Image** - the container image a sandbox starts from. It must contain the agent, e.g. `claude-sandbox` or `opencode-sandbox` built from the Dockerfiles in this repo.
* **Sandbox** - a running, isolated container created from an image, with one or more providers attached, running a main command. The sandbox stops when that command exits.
* **Policy and rules** - what a sandbox may access. A policy file sets filesystem access, providers add network access, and you approve or reject further network rules as the agent gets blocked. See [Sandbox policies](#sandbox-policies).

### Basic steps
1. [Set up Podman](#podman) and [install OpenShell](#install-openshell).
2. [Put your key or token in `.env`](#credentials-in-env).
3. For an agent ([Claude Code](#claude-code-with-a-claude-subscription) or [OpenCode](#opencode-with-openrouter)): import its profile, create a provider, build its image.
4. [Start and use a sandbox](#start-and-use-a-sandbox), with the agent in your terminal or with VS Code. By hand (for OpenCode: image `opencode-sandbox:latest`, provider `openrouter`, agent `opencode`):
``` shell
# once: create a sandbox that keeps running
openshell sandbox create --name my-task --from claude-sandbox:latest --provider claude \
  --policy policies/vscode-terminal.yaml --detach -- sleep infinity

# then, as often as you like:
openshell sandbox exec my-task --workdir /sandbox -- claude-start   # agent in this terminal
openshell sandbox connect my-task --editor vscode                   # VS Code
```
Or with the script, which creates the sandbox on first use:
``` shell
./sandbox.sh claude my-task            # agent in this terminal
./sandbox.sh claude my-task --vscode   # the same sandbox in VS Code
```
5. In VS Code, start the agent in the integrated terminal (`claude-start` or `opencode`).
6. Open a shell in the sandbox when you need one, with `sandbox exec` or plain SSH:
``` shell
openshell sandbox exec my-task --workdir /sandbox -- bash

# SSH: add the host entry once (already there after a --editor vscode connect)
openshell sandbox ssh-config my-task >> ~/.ssh/config
ssh openshell-my-task.default
```
7. [Move code in and out](#getting-code-in-and-out) with git bundles, then review, push and open the MR from your machine:
``` shell
./bundle.sh in  my-task ./myrepo   # repo into /sandbox/myrepo, on branch agent/my-task
./bundle.sh out my-task ./myrepo   # the agent's commits back as branch agent/my-task
```
8. [Approve or reject network rules](#network-rules) when the agent gets blocked.

If something fails, see [Troubleshooting](#troubleshooting).

# Setup
## Podman
OpenShell runs the sandboxes in a container runtime. These steps use Podman (5.x is required). OpenShell can also use Docker (28.0 or later) or MicroVMs.

### macOS (Apple Silicon)
On macOS, Podman runs containers in a Linux VM called a Podman machine.

* Install Podman, either with the installer from [podman.io](https://podman.io/) (the Podman docs recommend this) or with Homebrew:
``` shell
brew install podman
```

* Create and start the Podman machine:
``` shell
podman machine init
podman machine start
```

* Verify the version is 5.x and that containers run:
``` shell
podman --version
podman run --rm quay.io/podman/hello
```

### Linux
Podman on Linux needs cgroups v2 and an active Podman user socket.

* Install Podman, e.g. `sudo apt install podman` or `sudo dnf install podman`
* Start the user socket, and enable it so it starts at login:
``` shell
systemctl --user enable --now podman.socket
```

* Check that cgroups v2 is used (should print `v2`):
``` shell
podman info --format '{{.Host.CgroupsVersion}}'
```

## Install OpenShell
* Run the installer. It installs the CLI, the policy prover and a local gateway. On macOS it uses Homebrew and runs the gateway as a Homebrew service at `https://localhost:17670`. On Linux it runs as a systemd user service.
``` shell
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
```

### Use Podman for the gateway
If you don't set a driver, the gateway auto-detects one. It tries Kubernetes first, then Podman, then Docker. To make sure it uses Podman, set the driver in `~/.config/openshell/gateway.toml`:
``` toml
[openshell.gateway]
compute_driver = "podman"
```
The gateway finds the Podman socket by itself, including the `podman machine` socket on macOS.

* Validate the config, then restart the gateway:
``` shell
openshell-gateway config preflight --path ~/.config/openshell/gateway.toml

# macOS
brew services restart openshell
# Linux
systemctl --user restart openshell-gateway
```

### Verify the installation
``` shell
openshell status
```
* If something is wrong, check the gateway service: `brew services list` on macOS, or `journalctl --user -u openshell-gateway -f` on Linux
* Quick test with the default sandbox image (a minimal Ubuntu without an agent):
``` shell
openshell sandbox create --name demo
```

## Credentials in .env
Keys and tokens go in `.env` in this folder. Start from the template; `.env` is ignored by git (see [.gitignore](.gitignore)):
``` shell
cp .env.example .env
```
Then fill in the values, e.g.:
```
OPENROUTER_API_KEY=sk-or-...
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```
`openshell provider create --from-existing` reads them from the environment, so they must be *exported*. A plain `source .env` doesn't export lines without `export`. Load the file in a subshell, only for the command that needs it:
``` shell
(set -a; . ./.env; openshell provider create ...)
```
* `set -a` exports the variables, so `openshell` can read them.
* The parentheses run everything in a subshell. The secrets are gone when it ends, so they don't stay in your terminal's environment, where every program you start later would get them.
* `.env` should only be readable by you: `chmod 600 .env`

# Agents
Both agent chapters follow the same steps: profile, provider, image, sandbox.

## Claude Code with a Claude subscription
Claude Code runs with a Claude subscription (Pro/Max) via an OAuth token, not an API key. The upstream [claude-code.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/claude-code.yaml) profile only supports API keys, so this repo has its own profile: [providers/claude-code-oauth.yaml](providers/claude-code-oauth.yaml). It injects the token as `Authorization: Bearer` only on requests to the endpoints listed in the profile (`api.anthropic.com` and `platform.claude.com`), so the real token never lives inside the sandbox.

### Create an OAuth token (on the host)
Run on your own machine. It opens the browser to log in with your Claude account and prints a long-lived (1 year) token:
``` shell
claude setup-token
```
* Add the token to `.env` as `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...`

### Import the profile
``` shell
openshell provider profile lint   -f providers/claude-code-oauth.yaml
openshell provider profile import -f providers/claude-code-oauth.yaml
```
* After editing the file later, use `update` instead of `import`. See [Update a profile](#update-a-profile).

### Create the provider
The profile is only a template. The provider is the instance that holds your token in the gateway, and it is what a sandbox refers to with `--provider`. Importing the profile does not create the provider.

* Check that the profile is imported; `claude-code-oauth` should be listed:
``` shell
openshell provider profile list
```

* Load `.env` (see [Credentials in .env](#credentials-in-env)) and create the provider:
  * `--name` is your own name for the provider, used later with `--provider claude`
  * `--type` is the `id` of the profile in [providers/claude-code-oauth.yaml](providers/claude-code-oauth.yaml)
``` shell
(set -a; . ./.env; openshell provider create \
  --name claude \
  --type claude-code-oauth \
  --from-existing)
```
Expected output: `✓ Created provider claude`

* Verify; `claude` should be listed with type `claude-code-oauth` and 1 credential key:
``` shell
openshell provider list
```
```
NAME        TYPE               CREDENTIAL_KEYS   CONFIG_KEYS
claude      claude-code-oauth  1                 0
```

### Build the image
There is no ready-made image, so build one from [Dockerfile.claudecode](Dockerfile.claudecode). It is `node:22-slim` with `git` and Claude Code (installed via npm), plus a `claude-start` wrapper that skips Claude Code's first-run onboarding and then starts `claude`.
``` shell
podman build -t claude-sandbox:latest -f Dockerfile.claudecode .
```

Why the wrapper is needed: onboarding runs a connectivity check that connects to `api.anthropic.com` without going through the OpenShell proxy. The sandbox denies that connection, and Claude Code exits with `Failed to connect to api.anthropic.com: EACCES`. The wrapper writes `{"hasCompletedOnboarding": true}` to `~/.claude.json` (`/sandbox/.claude.json`) on first start, so the check is skipped. All other traffic goes through the proxy and works.

### Create the sandbox
Quickest: `./sandbox.sh claude [name]` for Claude in your terminal, or add `--vscode` for VS Code. See [Start a sandbox](#start-and-use-a-sandbox). The sections below show what it does by hand.

Always start Claude with `claude-start`, not `claude`.

#### With VS Code and a terminal (recommended)
The sandbox runs `sleep infinity` as its main process, so it keeps running while you start and quit Claude. The [terminal policy](#filesystem-policy) lets VS Code open terminals inside it.
``` shell
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
``` shell
cd /sandbox/myrepo
claude-start
```
* **From a terminal on your machine:**
``` shell
openshell sandbox exec claude-agent1 --tty --workdir /sandbox/myrepo -- claude-start
```
* You can run several Claude sessions in the same sandbox, e.g. one per terminal tab.

#### Claude as the main process
Simpler, but the sandbox stops (`Completed`) when you quit Claude, and VS Code can no longer connect.
``` shell
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
* **Binary paths** - only the binaries listed in the profile may reach the endpoints and get the token. The profile covers `/usr/bin/claude`, `/usr/local/bin/claude` and the npm install path `/usr/local/lib/node_modules/@anthropic-ai/**`. If requests are denied, check `openshell logs claude-agent1` for the blocked binary path, add it to `binaries` and [update the profile](#update-a-profile).
* **Don't use `/login` inside the sandbox** - an interactive login would store the OAuth credentials in the sandbox (`~/.claude/.credentials.json`) and needs extra login hosts opened. `setup-token` + provider keeps the token outside.
* **Token expiry** - the token is valid for a year. Regenerate with `claude setup-token`, put the new token in `.env`, and update the provider:
``` shell
(set -a; . ./.env; openshell provider update claude --from-existing)
```
* **Only Anthropic hosts in the profile** - OpenShell swaps the token placeholder for the real token on requests to *every* host in the profile. Shared third-party services such as `sentry.io` would let a manipulated agent send the token, or your code, to someone else's account, so the profile lists only `api.anthropic.com` and `platform.claude.com`. The image sets `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, so Claude Code doesn't try to send telemetry, error reports or update checks (`statsig.anthropic.com`, `sentry.io`, Datadog).
* **The Claude Code VS Code extension** would run its own bundled `claude` binary from `~/.vscode-server/extensions/...`, which isn't in the profile's `binaries` list, so its requests will most likely be denied (not tested). Use the CLI in the terminal instead.

## OpenCode with OpenRouter
OpenCode uses models through the OpenRouter API, with an OpenRouter API key.

### Import the profile
The profile describes the OpenRouter API, not OpenCode: the API key, the host `openrouter.ai`, and which binary may use the key. This repo has a local copy of the upstream profile: [providers/openrouter.yaml](providers/openrouter.yaml). It doesn't change with upstream, and only `/usr/local/bin/opencode` may use the key, the opencode path in the image.
``` shell
openshell provider profile lint   -f providers/openrouter.yaml
openshell provider profile import -f providers/openrouter.yaml
```
* After editing the file later, use `update` instead of `import`. See [Update a profile](#update-a-profile).
* To use the upstream version directly instead: `openshell provider profile import --url https://raw.githubusercontent.com/NVIDIA/OpenShell/main/providers/openrouter.yaml`

### Create the provider
* Put the key in `.env` as `OPENROUTER_API_KEY=sk-or-...`, load it (see [Credentials in .env](#credentials-in-env)) and create the provider:
``` shell
(set -a; . ./.env; openshell provider create \
  --name openrouter \
  --type openrouter \
  --from-existing)
```
* Verify with `openshell provider list`.

### Build the image
The official image `ghcr.io/anomalyco/opencode:latest` is Alpine-based and has no `git` or `bash`, and its entrypoint is `opencode`. [Dockerfile.opencode](Dockerfile.opencode) builds on it:
* adds `git` (for [getting code in and out](#getting-code-in-and-out)), `bash` (VS Code's terminal), `libstdc++` (needed by VS Code Server on Alpine) and `script`
* clears the entrypoint, so the command after `--` (e.g. `sleep infinity`) runs as is
* keeps `opencode` at `/usr/local/bin/opencode`, the only path the `openrouter` profile lets use the API key
``` shell
podman build -t opencode-sandbox:latest -f Dockerfile.opencode .
```

### Create the sandbox
Quickest: `./sandbox.sh opencode [name]` for OpenCode in your terminal, or add `--vscode` for VS Code. See [Start a sandbox](#start-and-use-a-sandbox). The sections below show what it does by hand.

#### With VS Code and a terminal (recommended)
``` shell
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
``` shell
cd /sandbox/myrepo
opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```
* **From a terminal on your machine:**
``` shell
openshell sandbox exec opencode-agent2 --tty --workdir /sandbox -- opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```

#### OpenCode as the main process
Uses the official image directly. The sandbox stops when you quit OpenCode, and the image doesn't support VS Code's terminal.
``` shell
openshell sandbox create \
  --name opencode-agent1 \
  --from ghcr.io/anomalyco/opencode:latest \
  --provider openrouter \
  -- opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```

### Things to watch for
* **Binary path** - only `/usr/local/bin/opencode` may use the key. If you install OpenCode elsewhere (e.g. via npm), add that path to the profile and [update it](#update-a-profile).
* **Hosts left blocked** - OpenCode tries `models.opencode.ai` (model list) and `registry.npmjs.org` (update check). Both are denied. OpenCode works without them, so leave them blocked unless you need them.
* **The sandbox user** is uid 1000 with `HOME=/sandbox`.

# Working in sandboxes
The examples use `claude-agent1`. Everything works the same for the OpenCode sandboxes.

## Start and use a sandbox
Create a sandbox once, then use it as often as you like: with the agent in your terminal, with VS Code, or both. The sandbox runs `sleep infinity` as its main process, so it keeps running when you quit the agent or close VS Code, and the files stay.

You can do this by hand or with [sandbox.sh](sandbox.sh). The values per agent:

| Agent | Image | Provider | Agent command |
|---|---|---|---|
| Claude Code | `claude-sandbox:latest` | `claude` | `claude-start` |
| OpenCode | `opencode-sandbox:latest` | `openrouter` | `opencode -m openrouter/nvidia/nemotron-3.5-lightning:free` |

The examples below use Claude and the sandbox name `my-task`.

### By hand
1. **Create the sandbox** (once):
``` shell
openshell sandbox create \
  --name my-task \
  --from claude-sandbox:latest \
  --provider claude \
  --policy policies/vscode-terminal.yaml \
  --detach \
  -- sleep infinity
```
* `--detach` returns right away and leaves `sleep infinity` running in the background.
* `--policy` adds terminal access, which VS Code's terminal needs (see [Filesystem policy](#filesystem-policy)).
* Wait until `openshell sandbox list` shows `my-task` as `Ready`.

2. **Use the agent in your terminal:**
``` shell
openshell sandbox exec my-task --workdir /sandbox -- claude-start
```
* `--workdir` is the folder the agent starts in, e.g. `/sandbox/myrepo`.
* Arguments after the agent command go to the agent, e.g. `... -- claude-start -p 'reply with OK'` as a smoke test.
* Quit the agent as usual. The sandbox keeps running.

3. **Or use VS Code:**
``` shell
openshell sandbox connect my-task --editor vscode
```
* VS Code opens a window connected to the sandbox. Open a folder with *File > Open Folder*, and start the agent in *Terminal > New Terminal* with `claude-start`.
* See [VS Code](#vs-code) for the one-time setup.

4. **Or open a shell in the sandbox** to look around or run commands:
``` shell
openshell sandbox exec my-task --workdir /sandbox -- bash
```
* Leave the shell with `exit` or Ctrl-D. The sandbox keeps running.
* The shell has the same restrictions as the agent, and the provider's credentials as placeholders, so you can start `claude-start` or `opencode` from it too.
* **A single command, no shell:**
``` shell
openshell sandbox exec my-task -- ls -la /sandbox
```
* **Plain SSH:** after you've connected a sandbox once with `--editor vscode`, it has an SSH host entry (`openshell-<name>.default`), so this works:
``` shell
ssh openshell-my-task.default
```
For other sandboxes, add the entry first:
``` shell
openshell sandbox ssh-config my-task >> ~/.ssh/config
```
The entry tunnels SSH through the gateway with `openshell ssh-proxy`, so the sandbox doesn't need an open port. `scp` doesn't work over this connection and the images have no `rsync`. To copy files, use `openshell sandbox upload` and `download` (see [Getting code in and out](#getting-code-in-and-out)).

5. **Later:** check that the sandbox is still running, and use it again with step 2, 3 or 4:
``` shell
openshell sandbox list
```
* `Ready`: running, use it.
* `Completed` or `Error`: stopped. Delete it and create it again (step 1). Files in it are lost, so get your work out first (see [Getting code in and out](#getting-code-in-and-out)).

6. **When the task is done:**
``` shell
openshell sandbox delete my-task
```

### With the script
[sandbox.sh](sandbox.sh) does steps 1 to 3 in one command. It creates the sandbox on first use and reuses it after that:
``` shell
./sandbox.sh <claude|opencode> [name] [--vscode] [--workdir DIR] [-- agent args...]
```
| Command | What happens |
|---|---|
| `./sandbox.sh claude` | Claude in this terminal, in sandbox `claude-agent1` |
| `./sandbox.sh claude my-task` | Claude in this terminal, in sandbox `my-task` |
| `./sandbox.sh claude my-task --vscode` | Opens sandbox `my-task` in VS Code; start Claude in its terminal |
| `./sandbox.sh opencode` | OpenCode in this terminal, in sandbox `opencode-agent1` |
| `./sandbox.sh claude my-task -w /sandbox/myrepo` | Claude starts in `/sandbox/myrepo` |
| `./sandbox.sh claude my-task -- -p 'reply with OK'` | Passes arguments to the agent (here: a non-interactive smoke test) |

* The script uses the image, provider and agent command from the table above. Set the OpenCode model with `OPENCODE_MODEL=...`.
* **Requirements:** the provider and image from the agent's chapter must exist.
* **A stopped sandbox** (`Completed` or `Error`) isn't reused. The script says so; delete it with `openshell sandbox delete <name>` and run the script again.
* For a shell, checking status and deleting, use steps 4 to 6 above.

## VS Code
VS Code connects to a sandbox over SSH with the Remote-SSH extension. OpenShell tunnels the SSH connection through the gateway, so the sandbox doesn't expose any port.

### One-time setup
* Install the [Remote-SSH](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-ssh) extension, and make sure the `code` command works in a terminal (in VS Code: *Shell Command: Install 'code' command in PATH*).
* Add this to your VS Code user settings (`settings.json`):
``` json
"remote.SSH.localServerDownload": "always",
```
VS Code installs "VS Code Server" in the sandbox on first connect. By default the sandbox downloads it itself, which fails because the sandbox can't reach Microsoft's servers. With this setting, your machine downloads it and copies it in over SSH.

### Connect
The sandbox must be running (`Ready` in `openshell sandbox list`) and created with `--policy policies/vscode-terminal.yaml`, otherwise VS Code's terminal won't start.
``` shell
openshell sandbox connect claude-agent1 --editor vscode
```
* This opens a VS Code window connected to the sandbox. Use *File > Open Folder* to open e.g. `/sandbox/myrepo`.
* The first connect takes up to a minute while VS Code Server is copied in. Later connects are quick.
* The VS Code terminal runs inside the sandbox, with the same restrictions as the agent. It gets the provider's credentials as placeholders (`openshell:...`), so the agent works there.
* You can also pass `--editor vscode` when you create a sandbox: `openshell sandbox create --editor vscode ...`
* OpenShell adds `Include "~/.config/openshell/ssh_config"` to `~/.ssh/config`, with one host per sandbox, e.g. `openshell-claude-agent1.default`. These hosts also show up in VS Code's *Remote Explorer*, and plain `ssh openshell-claude-agent1.default` works too.
* Without `--editor`, `openshell sandbox ssh-config claude-agent1` prints the host entry so you can add it yourself.

### Things to watch for
* **Blocked hosts** - VS Code Server tries to reach `main.vscode-cdn.net` and `mobile.events.data.microsoft.com` (telemetry). The logs show these as `DENIED`. Editing works without them, so leave them blocked.
* **Extensions in the sandbox** - installing extensions on the remote side needs marketplace access, which is blocked. Add `"remote.downloadExtensionsLocally": true` to the settings, so VS Code downloads extensions on your machine and copies them in.
* **Don't approve rules for VS Code's `node`** - the binary path contains the VS Code version (`/sandbox/.vscode-server/cli/servers/Stable-<hash>/server/node`), so an approved rule stops matching after a VS Code update.
* **Edits go into the sandbox** - files you edit live in the sandbox, not on your machine. Get them out with git as described in [Getting code in and out](#getting-code-in-and-out).

## Getting code in and out
The examples use a repo at `./myrepo`. The image needs `git`; both images from this repo have it.

There are three ways to do it, from safest to most convenient:

| Approach | Git credentials in sandbox | Who pushes and opens the MR |
|---|---|---|
| 1. Git bundles in and out (recommended) | None | You, from the host |
| 2. Read-only clone in the sandbox, bundle out | Read-only | You, from the host |
| 3. Push from inside the sandbox | Write access, scoped to one repo | The agent |

### Good to know about upload and download
* `openshell sandbox upload <sandbox> <local-path> <dest>` puts a folder *inside* `<dest>`. Uploading `./myrepo` to `/sandbox/myrepo` gives `/sandbox/myrepo/myrepo`, so upload to `/sandbox` instead.
* `upload` follows `.gitignore` and leaves out the `.git` folder, so an uploaded repo has no history. Use a git bundle (below) to keep the history.
* `openshell sandbox download <sandbox> <sandbox-path> <local-dest>` copies files back to the host.
* `--upload` on `sandbox create` can't be combined with a command after `--`. Upload into a running sandbox instead.

### 1. Git bundles in and out (recommended)
A git bundle is a single file that contains commits, like a portable remote. The sandbox never gets git credentials or network access to your git host, and you review everything before it leaves your machine.

#### With the script
[bundle.sh](bundle.sh) does the steps below in two commands:
``` shell
./bundle.sh in  <sandbox> <repo> [--branch NAME] [--base BRANCH]
./bundle.sh out <sandbox> <repo> [--branch NAME] [--base BRANCH] [--force]
```
A typical task, with the sandbox `my-task` and the repo `./myrepo`:
``` shell
./bundle.sh in my-task ./myrepo
# the agent works in /sandbox/myrepo and commits on branch agent/my-task
./bundle.sh out my-task ./myrepo
git -C ./myrepo diff main...agent/my-task      # review
git -C ./myrepo push origin agent/my-task      # then open the MR
```
* **`in`** bundles only the base branch (`main`) and uploads it. Other branches and their history never reach the sandbox.
  * The first time, it creates `/sandbox/<repo-name>` and checks out the work branch from `main`. The branches from your machine are available as `host/*`, e.g. `host/main`, and the agent's git name and email are set.
  * Run it again to bring in newer commits from your machine. They arrive in `host/*` without touching the work branch; ask the agent to merge or rebase `host/main` if needed.
* **`out`** bundles the work branch's commits that aren't in `host/main`, downloads them and fetches them into your repo as the same branch. It then shows the log and a diff summary.
  * Only commits are taken out. It warns if there are uncommitted changes in the sandbox.
  * The branch must not be checked out in your repo on the host.
  * If the agent rebased, the branch has diverged from the copy on your machine, and `out` stops. Run it with `--force` to overwrite your copy.
* **Options:** `--branch` sets the work branch (default `agent/<sandbox>`) and `--base` the branch to start from and compare with (default `main`).

#### By hand

* Pack the repo on the host and upload it:
``` shell
git -C ./myrepo bundle create ../in.bundle --all
openshell sandbox upload claude-agent1 ./in.bundle /sandbox
```

* Clone it inside the sandbox on a work branch, e.g. ask the agent to do it, or run:
``` shell
openshell sandbox exec claude-agent1 -- sh -c '
  git clone -q /sandbox/in.bundle /sandbox/myrepo &&
  cd /sandbox/myrepo &&
  git config user.name "Claude (sandbox)" &&
  git config user.email "claude@sandbox.local" &&
  git checkout -b agent/my-task'
```

* Let the agent work and commit on `agent/my-task`. Then pack the new commits and download them:
``` shell
openshell sandbox exec claude-agent1 -- \
  git -C /sandbox/myrepo bundle create /sandbox/out.bundle main..agent/my-task
openshell sandbox download claude-agent1 /sandbox/out.bundle .
```

* Fetch the branch into your repo, review it, then push and open the MR yourself:
``` shell
git -C ./myrepo fetch ../out.bundle agent/my-task:agent/my-task
git -C ./myrepo log --oneline main..agent/my-task
git -C ./myrepo diff main agent/my-task
git -C ./myrepo push origin agent/my-task
```

* To give the sandbox newer commits from `main`, create a new `in.bundle`, upload it again, and run `git fetch /sandbox/in.bundle main:main` inside the sandbox.

### 2. Read-only clone in the sandbox
Attach a git provider that only allows reads, so the agent can clone and fetch by itself. Get the results out with a bundle as in approach 1. The upstream [github.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/github.yaml) profile works this way: it allows clone and fetch, but not push.
``` shell
openshell provider profile import --url https://raw.githubusercontent.com/NVIDIA/OpenShell/main/providers/github.yaml
GITHUB_TOKEN=<read-only-token> openshell provider create --name github-ro --type github --from-existing
openshell sandbox create ... --provider claude --provider github-ro ...
```
* There is no upstream GitLab profile. For GitLab, write your own for your GitLab host (see [Provider profiles](#provider-profiles)).

### 3. Push from inside the sandbox
Possible, but a sandbox that can push can also send your code anywhere the token reaches. Only do this when you trust the setup, and limit it:
* Use a token limited to one repository (e.g. a GitHub fine-grained token or a GitLab project access token).
* Allow pushes (`git-receive-pack`) for that one repository only, with a policy applied by `openshell policy set`. The official [GitHub Push Access tutorial](https://docs.nvidia.com/openshell/tutorials/github-push-access) shows the exact policy.
* Protect `main` on the git server. The policy can limit which repository, but not which branch.
* Opening the MR or PR from inside also needs `gh` or `glab` in the image, and API access to that repository in the policy.

## Many sandboxes in parallel
* **One sandbox per task or branch**, named after the task (`claude-auth-fix`, `claude-docs`). Each has its own filesystem, policy and approved rules, so agents don't interfere with each other.
* **Providers are shared** - create a provider once and attach it to every sandbox with `--provider`.
* **Labels** - add e.g. `--label project=foo --label task=auth` on create, then list with `openshell sandbox list --selector project=foo`.
* **Templates** - store the image and resources once, then create sandboxes from it. `--template` can't be combined with `--from`, `--cpu`, `--memory` or `--env`:
``` shell
openshell sandbox template create claude --image claude-sandbox:latest --cpu 2 --memory 4Gi
openshell sandbox create --name claude-auth-fix --template claude --provider claude \
  --policy policies/vscode-terminal.yaml --detach -- sleep infinity
```
* **Resources** - all sandboxes run inside the one Podman machine. Give it room if you run several:
``` shell
podman machine stop
podman machine set --cpus 6 --memory 12288
podman machine start
```
* **Usage limits** - parallel Claude sessions share your Claude subscription's limits.
* **Approved rules are per sandbox** and reset when the sandbox is recreated. Hosts every sandbox needs belong in the profile or in a policy file.
* **Overview and cleanup** - `openshell sandbox list`, and `openshell sandbox delete <sandbox>` when a task is done.

# Customizing
## Provider profiles
A profile is a YAML file that you write yourself or download, and then import into the gateway. No command generates it.
* **Ready-made profiles** are in the [OpenShell repo](https://github.com/NVIDIA/OpenShell/tree/main/providers). [providers/openrouter.yaml](providers/openrouter.yaml) is a local copy of one.
* **Custom profiles** like [providers/claude-code-oauth.yaml](providers/claude-code-oauth.yaml) are written by hand. That one is based on the upstream [claude-code.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/claude-code.yaml), changed to use an OAuth token instead of an API key.

### Fields
| Field | Purpose | Example (claude-code-oauth) |
|---|---|---|
| `id` | The profile's name, passed to `--type` when creating a provider | `claude-code-oauth` |
| `credentials` | The secret it needs, the environment variable it's read from, and how it's added to requests | `CLAUDE_CODE_OAUTH_TOKEN`, sent as `Authorization: Bearer` |
| `endpoints` | Hosts and ports the agent may reach. The credential is added only on requests to these | `api.anthropic.com:443`, `platform.claude.com:443` |
| `binaries` | Programs inside the sandbox that may use those endpoints | `/usr/local/lib/node_modules/@anthropic-ai/**` |
| `discovery` | Credentials that `--from-existing` looks for in the environment | `oauth_token` |
| `display_name`, `description`, `category`, `inference_capable` | Labels and metadata | `agent`, `true` |

### Minimal example
``` yaml
id: my-agent
display_name: My agent
description: My agent with an API key
category: agent
inference_capable: true
credentials:
  - name: api_key
    description: API key for api.example.com
    env_vars: [MY_AGENT_API_KEY]   # read from the environment by --from-existing
    required: true
    auth_style: bearer             # sent as "Authorization: Bearer <key>"
    header_name: authorization
discovery:
  credentials: [api_key]
endpoints:
  - host: api.example.com
    port: 443
    protocol: rest
    access: read-write
    enforcement: enforce
binaries:
  - /usr/local/bin/my-agent        # the agent's path inside the image
```

### Create a profile
1. Start from a similar profile. Export one that's already in the gateway with `openshell provider profile export <id>`, or copy one from the OpenShell repo.
2. Edit `id`, `credentials`, `endpoints` and `binaries`. To find the right binary path, run the agent once and check `openshell logs <sandbox> | grep DENIED`.
3. Validate and import it, then check the result:
``` shell
openshell provider profile lint   -f providers/my-agent.yaml
openshell provider profile import -f providers/my-agent.yaml
openshell provider profile describe my-agent
```
4. Create a provider from it with `openshell provider create --type my-agent ...`

### Update a profile
`import` and `lint` fail once the profile exists (`custom provider profile '...' already exists`). Use `update` instead. It needs the current `resource_version` from the gateway, so the commands below read it and add it to a temporary copy of the file. Set `ID` to the profile's id, e.g. `claude-code-oauth` or `openrouter`:
``` shell
ID=claude-code-oauth
V=$(openshell provider profile export $ID | awk '/^resource_version:/{print $2}')
sed "s/^id: $ID\$/&\nresource_version: $V/" providers/$ID.yaml > /tmp/$ID.yaml
openshell provider profile update $ID -f /tmp/$ID.yaml
openshell provider profile describe $ID
```
* The existing provider picks up the change. Sandboxes created after the update get the new endpoints.

## Sandbox policies
What a sandbox may access comes from three places:
* **The policy file** (`--policy`) sets filesystem access. Without it, a sandbox gets OpenShell's built-in default.
* **The attached providers** add network access to the hosts in their profiles.
* **Network rules** you approve add more hosts, per sandbox.

### Filesystem policy
This repo has two policies. The one used everywhere is [policies/vscode-terminal.yaml](policies/vscode-terminal.yaml). It is the default policy plus `/dev/pts` and `/dev/ptmx`, so programs inside the sandbox can open terminals. VS Code's integrated terminal needs this; without it, it fails with `forkpty(3) failed`.
``` yaml
version: 1
filesystem_policy:
  include_workdir: true        # the workdir (/sandbox) is read-write
  read_only:
    - /bin
    - /usr
    - /lib
    - /proc
    - /dev/urandom
    - /etc
    - /var/log
  read_write:
    - /tmp
    - /dev/null
    - /dev/pts                 # added: terminals (VS Code's terminal)
    - /dev/ptmx                # added: terminals (VS Code's terminal)
landlock:
  compatibility: best_effort
```
* `read_only` and `read_write` list the only paths the sandbox's processes may access. Everything else is blocked (enforced with Landlock).
* `include_workdir: true` makes the working directory (`/sandbox`, also `$HOME`) read-write.
* There is no `network_policies` section, so network access comes only from the attached providers and approved rules.

Create your own:
1. Start from [policies/example.yaml](policies/example.yaml) (see [Example policy with network rules](#example-policy-with-network-rules)), or from the default policy of an existing sandbox. `--base` leaves out the provider's network rules, and the `sed` drops the header lines before the YAML:
``` shell
openshell policy get claude-agent1 --base | sed -n '/^version:/,$p' > policies/my-policy.yaml
```
2. Edit the file, e.g. add paths to `read_only` or `read_write`. Only add what's needed: every path you add is something the agent can reach too.
3. Network rules that every sandbox needs can go in a `network_policies` section, as in the example below. For a provider's own hosts, prefer the profile's `endpoints`.

Use it:
* Pass it with `--policy policies/my-policy.yaml` when you create the sandbox.
* Check what the sandbox got: `openshell policy get claude-agent1 --base`, or `--full` to include the provider's network rules.
* **Filesystem changes need a new sandbox.** Filesystem rules are fixed when the sandbox starts. `openshell policy set` on a running sandbox loads the new version, but processes still can't access the new paths. Delete the sandbox and create it again with `--policy`.
* **Network changes apply right away.** `openshell policy set <sandbox> --policy <file> --wait` hot-reloads `network_policies` without recreating the sandbox. `policy set` replaces the whole base policy, so start from `openshell policy get <sandbox> --base` and keep its filesystem part unchanged.

### Example policy with network rules
[policies/example.yaml](policies/example.yaml) is the terminal policy plus five network rules, as a starting point for your own policies. The paths are for the `claude-sandbox` image.

| Rule | Allows | Blocks |
|---|---|---|
| `python_docs` | Claude Code (`claude.exe`) reading `docs.python.org`, e.g. with its WebFetch tool | Other programs, and anything but GET/HEAD/OPTIONS (`access: read-only`) |
| `npm_registry` | `node` (which runs npm) downloading packages from `registry.npmjs.org` | Writes such as `npm login` or `npm publish` |
| `github_clone` | `git clone` and `fetch` from GitHub, via git's HTTPS helper `git-remote-http` | `git push` (explicit `deny_rules`), and other git hosts |
| `context7_mcp` | Claude Code using the Context7 MCP server (library docs): connecting, listing tools, and the tools `resolve-library-id` and `query-docs` | Every other MCP method and tool |
| `huggingface_mcp` | Claude Code using the Hugging Face MCP server: all standard MCP methods, and tools matching `hub_repo_*` | Other tools, and `hf_fs` explicitly (`deny_rules`) |

The structure of a rule:
``` yaml
network_policies:
  npm_registry:                    # rule name (any)
    name: npm-registry
    endpoints:                     # where to
      - host: registry.npmjs.org
        port: 443
        protocol: rest             # inspect each HTTP request...
        access: read-only          # ...and allow only GET, HEAD and OPTIONS
        enforcement: enforce       # block violations (audit only logs them)
    binaries:                      # who may connect
      - path: /usr/local/bin/node
```
* **Binaries:** list the program that actually opens the connection, by its real path (check with `readlink -f` inside the sandbox). For npm that's `node`, and for git over HTTPS it's `/usr/lib/git-core/git-remote-http`. The `DENIED` lines in `openshell logs <sandbox>` show the path OpenShell saw.
* **`access` or `rules`:** `access` is a preset (`read-only`, `read-write`, `full`). `rules` allow specific methods, paths and query parameters, as in `github_clone`. An endpoint uses one or the other.
* **`deny_rules`** always win over allow rules. Use them to make a ban explicit.
* **Without `protocol`**, OpenShell only checks host, port and binary, and allows any request.
* **Credentials:** a network rule never sends provider credentials. Those only go to the hosts in the provider's profile.

**Remote MCP servers** (`context7_mcp`, `huggingface_mcp`) use `protocol: mcp`. OpenShell then reads every MCP request and checks the method and, for `tools/call`, the tool name:
``` yaml
  context7_mcp:
    name: context7-mcp
    endpoints:
      - host: mcp.context7.com
        port: 443
        path: /mcp
        protocol: mcp
        enforcement: enforce
        mcp:
          versions: ["2025-03-26", "2025-06-18", "2025-11-25"]
        rules:
          - allow:
              method: initialize
          - allow:
              method: notifications/initialized
          - allow:
              method: tools/list
          - allow:
              method: tools/call
              tool:
                any: [resolve-library-id, query-docs]
    binaries:
      - path: /usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
```
* **Two styles:** list every allowed method, as in `context7_mcp`. Or set `allow_all_known_mcp_methods: true` and only restrict the tools, as in `huggingface_mcp`, which allows `tool: "hub_repo_*"` and denies `hf_fs`.
* **`mcp.versions`:** the default is only `2025-11-25`. Clients send `initialize` without a version header, which counts as `2025-03-26`, so list that too.
* **Binary:** Claude Code connects to remote MCP servers itself, so the binary is `claude.exe`. Add the server in Claude Code as usual, e.g. `claude mcp add --transport http context7 https://mcp.context7.com/mcp`.
* **Tool arguments aren't checked.** An allowed tool can be called with any arguments.
* **Servers that need a login:** put the token in a provider profile with the server's host as endpoint, and attach the provider. Never put tokens in a policy.
* **Claude Code asks every server for `prompts/list` and `resources/list`.** With an explicit method list like `context7_mcp`, these appear as `DENIED` in the logs. That's harmless.

Tested in a sandbox:
* `npm_registry`: GET returned 200 and POST returned 403. `node` couldn't reach `docs.python.org`, because only Claude may use that rule.
* `github_clone`: a clone worked, a push was blocked with 403, and `gitlab.com` couldn't be reached.
* `python_docs`: Claude fetched the page.
* `context7_mcp`: Claude looked up a library ID through the MCP server.
* `huggingface_mcp`: `hub_repo_search` worked. `hf_whoami` was blocked ("no matching allow rule") and `hf_fs` was blocked ("blocked by a deny rule").

Use it as-is or copy it:
``` shell
cp policies/example.yaml policies/my-task.yaml   # then edit
openshell sandbox create --name my-task --from claude-sandbox:latest --provider claude \
  --policy policies/my-task.yaml --detach -- sleep infinity
```

### Network rules
A sandbox starts out mostly locked down. When the agent or another tool tries to reach a host that isn't allowed, the connection is denied and logged, and OpenShell proposes a rule that would allow it. Ask the agent to do what you want to allow (e.g. fetch a web page), then review the proposals. The examples use `opencode-agent1`.

* Check the logs:
``` shell
openshell logs opencode-agent1
openshell logs opencode-agent1 | grep DENIED
```

* List the pending proposals:
``` shell
openshell rule get opencode-agent1 --status pending
```

* Approve a proposal:
``` shell
openshell rule approve opencode-agent1 --chunk-id <chunk-id>
```
```
OK Chunk approved. Policy version: 2, hash: 896a5bc27d1f
```

* Or reject it, with a reason:
``` shell
openshell rule reject opencode-agent1 \
  --chunk-id <chunk-id> \
  --reason "Not needed for this task."
```
```
OK Chunk rejected.
```

* View the policy versions:
``` shell
openshell policy list opencode-agent1
```
```
VERSION  HASH           STATUS       CREATED                  ERROR
3        af2b9e891d51   Loaded       1791622741186
2        896a5bc27d1f   Superseded   1791622467183
1        a45a8ff3564f   Superseded   1791621734038
```

* View the approved rules:
``` shell
openshell rule get opencode-agent1 --status approved
```
```
Network Rules:  (version 4, 2 chunks)

  Chunk: ce757526-f94e-4b28-94bc-5f43a608f458
  Status: approved
  Rule: allow_www_dpreview_com_443
  Binary: /usr/local/bin/opencode
  Confidence: 65%
  Rationale: Allow opencode to connect to www.dpreview.com:443 (HTTPS).
  Prover: prover: no new findings
  Candidate: 35ee4f5e9cf9
  Endpoints: www.dpreview.com:443 [L4]
  Binaries: /usr/local/bin/opencode
  Hits: 3 (first seen 2026-10-10 08:47:48, last seen 2026-10-10 08:54:27)
```
* Approved rules apply only to that sandbox and reset when it is recreated. Hosts every sandbox needs belong in the profile's `endpoints`.

# Troubleshooting
Start with `openshell logs <sandbox> | grep DENIED` and `openshell sandbox get <sandbox>`.

| Symptom | Cause | Fix |
|---|---|---|
| `provider 'claude' not found and no provider profile named 'claude' is available` | The profile is imported, but the provider was never created | [Create the provider](#create-the-provider), then check `openshell provider list` |
| `provider create --from-existing` finds no credential | `.env` was loaded without exporting the variables | Run the command as `(set -a; . ./.env; openshell provider create ...)` |
| `custom provider profile '...' already exists` on `lint` or `import` | The profile is already in the gateway | Use `update` instead, see [Update a profile](#update-a-profile) |
| Claude: `Unable to connect to Anthropic services ... Failed to connect to api.anthropic.com: EACCES` | Claude Code's first-run connectivity check bypasses the proxy and is denied | Start with `claude-start`, not `claude` (see [Build the image](#build-the-image)). Also check the logs for other denied hosts |
| Log line `transparent TCP mapping is expired` | A connection to `api.anthropic.com` bypassed the proxy and was denied | Harmless on its own. Together with the `EACCES` error, see the row above |
| VS Code: `The terminal process failed to launch: ... forkpty(3) failed` | The sandbox was created without the terminal policy, so it can't open terminals | Check with `openshell policy get <sandbox> --base \| grep pts`. No output: delete the sandbox and create it again with `--policy policies/vscode-terminal.yaml`. `policy set` on a running sandbox doesn't help |
| VS Code hangs on first connect, `Downloading VS Code server` in the log | The sandbox can't download VS Code Server itself | Set `"remote.SSH.localServerDownload": "always"`, see [VS Code](#vs-code) |
| Sandbox is `Completed` or `Error`, VS Code can't connect | The main process (the agent) exited, and the sandbox stopped with it | Create the sandbox with `--detach -- sleep infinity` and run the agent in a terminal |
| Sandbox stuck in `Provisioning` after `openshell sandbox start` | The restart doesn't finish | Delete the sandbox and create it again |
| Requests from the agent denied, with a binary path in the log | The binary isn't in the profile's `binaries` list | Add the path to the profile and [update it](#update-a-profile) |
| A sandbox name can't be reused | The old sandbox with that name still exists | `openshell sandbox delete <sandbox>`, then create it again |

# References
## OpenShell
* [OpenShell on GitHub](https://github.com/NVIDIA/OpenShell)
* [Installation](https://docs.nvidia.com/openshell/about/installation)
* [Support matrix](https://docs.nvidia.com/openshell/latest/about/support-matrix)
* [Sandbox runtimes (Docker, Podman, MicroVM, Kubernetes)](https://docs.nvidia.com/openshell/how-it-works/sandboxes/runtimes)
* [Gateways overview](https://docs.nvidia.com/openshell/latest/how-it-works/gateways/overview)
* [Gateway configuration file](https://docs.nvidia.com/openshell/how-it-works/gateways/configuration)
* [Run your first agent](https://docs.nvidia.com/openshell/latest/about/run-your-first-agent)
* [Sandboxes overview (upload, download, exec, labels, editors)](https://docs.nvidia.com/openshell/how-it-works/sandboxes/overview)
* [Sandbox templates](https://docs.nvidia.com/openshell/how-it-works/sandboxes/templates)
* [GitHub push access tutorial](https://docs.nvidia.com/openshell/tutorials/github-push-access)
* [Security best practices](https://docs.nvidia.com/openshell/security/best-practices)
* Upstream provider profiles: [openrouter.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/openrouter.yaml), [claude-code.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/claude-code.yaml)

## Podman
* [Podman](https://podman.io/)
* [Podman Desktop on macOS](https://podman-desktop.io/docs/installation/macos-install)

## Agents
* [OpenCode image](https://github.com/anomalyco/opencode/pkgs/container/opencode)
* [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
* [OpenRouter](https://openrouter.ai/)
