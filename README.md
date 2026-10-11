# OpenShell configs
Configs and notes for running AI coding agents (Claude Code, OpenCode) in [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandboxes with Podman, editing their files in VS Code, and moving code in and out.

## Repository layout
| Path | What it is |
|---|---|
| [docs/](docs) | The full documentation, see [Documentation](#documentation) |
| [bin/](bin) | Scripts you run: [sandbox.sh](bin/sandbox.sh) starts an agent sandbox, [provider.sh](bin/provider.sh) creates a provider from `.env`, [bundle.sh](bin/bundle.sh) moves a git repo in and the agent's commits out, [watch-denied.sh](bin/watch-denied.sh) shows the denied connections as a live table, [otel-export.py](bin/otel-export.py) exports the logs as OpenTelemetry and [otel-view.py](bin/otel-view.py) shows them in the terminal, [acp_client.py](bin/acp_client.py) chats with an agent over ACP |
| [images/](images) | One folder per sandbox image, named after the image: [claude-sandbox](images/claude-sandbox) (Claude Code), [claude-browser](images/claude-browser) (Claude Code plus a headless browser), [opencode-sandbox](images/opencode-sandbox) (OpenCode) |
| [providers/](providers) | Provider profiles: [claude-code-oauth.yaml](providers/claude-code-oauth.yaml) (Claude subscription), [openrouter.yaml](providers/openrouter.yaml) (OpenRouter, for OpenCode) |
| [policies/](policies) | Sandbox policies: [vscode-terminal.yaml](policies/vscode-terminal.yaml) (the default plus terminals, used everywhere), [browser.yaml](policies/browser.yaml) (for the browser image), [example.yaml](policies/example.yaml) (network rules to copy and adapt) |
| [tests/](tests) | One folder per test, each run with its `run.sh`: [host-mcp](tests/host-mcp) (an MCP server on the host), [browser](tests/browser) (the headless browser) |
| [Makefile](Makefile) | `make images` builds all images in order, `make test` runs the tests, `make lint` checks the files |
| [.env.example](.env.example) | Template for `.env`, which holds your API key and token (ignored by git) |
| [.claude/skills/](.claude/skills/openshell-setup/SKILL.md) | A Claude Code skill that sets all of this up, step by step |
| [LICENSE](LICENSE) | MIT |

## Documentation
| Document | What's in it |
|---|---|
| [Setup](docs/setup.md) | Podman, installing OpenShell, credentials in `.env` |
| [Agents](docs/agents.md) | Claude Code with a Claude subscription, OpenCode with OpenRouter: profile, provider, image, sandbox |
| [Working in sandboxes](docs/working-in-sandboxes.md) | Starting and using a sandbox, VS Code, getting code and files in and out, viewing a web page, many sandboxes |
| [Extras](docs/extras.md) | MCP servers on the host, ACP, headless browser use |
| [Customizing](docs/customizing.md) | Provider profiles, sandbox policies, network rules |
| [Logging](docs/logging.md) | Reading the logs, watching denials live, OCSF JSON, exporting to OpenTelemetry and viewing the events |
| [Troubleshooting](docs/troubleshooting.md) | Symptoms, causes and fixes |

Commands in the docs run from the repo root.

## TL;DR
OpenShell runs AI coding agents in locked-down sandboxes. Agents get only the network access and credentials you allow, and API keys and tokens never enter the sandbox.

### Concepts
* **Gateway** - the local OpenShell server (`https://localhost:17670`) that manages everything below. It runs as a background service and starts sandboxes through a container runtime (here Podman).
* **Profile** - a template for a type of provider: which credential it needs (e.g. `CLAUDE_CODE_OAUTH_TOKEN`), which hosts it may reach, and which binaries may use it. A YAML file in [providers/](providers/), imported into the gateway. See [Provider profiles](docs/customizing.md#provider-profiles).
* **Provider** - an instance of a profile that holds your actual key or token, stored in the gateway. OpenShell's network proxy adds the credential to outgoing requests to the allowed hosts, so the agent never sees it.
* **Image** - the container image a sandbox starts from. It must contain the agent, e.g. `claude-sandbox` or `opencode-sandbox`, built from the folders in [images/](images).
* **Sandbox** - a running, isolated container created from an image, with one or more providers attached, running a main command. The sandbox stops when that command exits.
* **Policy and rules** - what a sandbox may access. A policy file sets filesystem access, providers add network access, and you approve or reject further network rules as the agent gets blocked. See [Sandbox policies](docs/customizing.md#sandbox-policies).

### Basic steps
1. [Set up Podman](docs/setup.md#podman) and [install OpenShell](docs/setup.md#install-openshell).
2. [Put your key or token in `.env`](docs/setup.md#credentials-in-env).
3. For an agent ([Claude Code](docs/agents.md#claude-code-with-a-claude-subscription) or [OpenCode](docs/agents.md#opencode-with-openrouter)): import its profile, create a provider (`bin/provider.sh claude` or `bin/provider.sh opencode` does both), build its image (`make images` builds all of them).
4. [Start and use a sandbox](docs/working-in-sandboxes.md#start-and-use-a-sandbox), with the agent in your terminal or with VS Code. By hand (for OpenCode: image `opencode-sandbox:latest`, provider `openrouter`, agent `opencode`):
```bash
# once: create a sandbox that keeps running
openshell sandbox create --name my-task --from claude-sandbox:latest --provider claude \
  --policy policies/vscode-terminal.yaml --detach -- sleep infinity

# then, as often as you like:
openshell sandbox exec my-task --workdir /sandbox -- claude-start   # agent in this terminal
openshell sandbox connect my-task --editor vscode                   # VS Code
```
Or with the script, which creates the sandbox on first use:
```bash
bin/sandbox.sh claude my-task            # agent in this terminal
bin/sandbox.sh claude my-task --vscode   # the same sandbox in VS Code
```
5. In VS Code, start the agent in the integrated terminal (`claude-start` or `opencode`).
6. Open a shell in the sandbox when you need one, with `sandbox exec` or plain SSH:
```bash
openshell sandbox exec my-task --workdir /sandbox -- bash

# SSH: add the host entry once (already there after a --editor vscode connect)
openshell sandbox ssh-config my-task >> ~/.ssh/config
ssh openshell-my-task.default
```
7. [Move code in and out](docs/working-in-sandboxes.md#getting-code-in-and-out) with git bundles, then review, push and open the MR from your machine:
```bash
bin/bundle.sh in  my-task ./myrepo   # repo into /sandbox/myrepo, on branch agent/my-task
bin/bundle.sh out my-task ./myrepo   # the agent's commits back as branch agent/my-task
```
   For single files, use `upload` and `download`. The destination is a folder, and the file keeps its name (see [Single files](docs/working-in-sandboxes.md#single-files)):
```bash
openshell sandbox upload   my-task ./notes.md /sandbox            # -> /sandbox/notes.md
openshell sandbox download my-task /sandbox/report.html .         # -> ./report.html
```
8. [Approve or reject network rules](docs/customizing.md#network-rules) when the agent gets blocked. `bin/watch-denied.sh` shows what is being blocked, live, across all sandboxes (see [Watching denials](docs/logging.md#watching-denials)).

### Optional
Not needed for the basic steps above. Each one gives the agent more reach, so add it when a task needs it.

#### MCP servers and ACP
* **Remote MCP servers** (HTTP): add them in the agent as usual and allow them with a `protocol: mcp` rule, which can limit the methods and tools. Tokens go in a provider, never in the policy. See [Example policy with network rules](docs/customizing.md#example-policy-with-network-rules).
* **Local MCP servers** (stdio, e.g. as container images): a sandbox can't run containers, so run the server on the host behind an HTTP bridge and use it like a remote server, by the host's IP. Its secrets stay on the host. See [MCP servers in containers on the host](docs/extras.md#mcp-servers-in-containers-on-the-host).
* **ACP:** to drive the agent from a UI on the host, `bin/sandbox.sh claude|opencode my-task --acp` runs its ACP server over stdin/stdout, without opening a port. To try it, chat with `bin/acp_client.py connect my-task`. See [ACP](docs/extras.md#acp-agent-client-protocol).

#### Headless browser use
* **What:** Claude Code uses a headless Chromium **inside the sandbox**, through Playwright MCP. The browser has none of your logins.
* **How:** build the `claude-browser` image, list the sites the browser may open in [policies/browser.yaml](policies/browser.yaml), and start with `bin/sandbox.sh claude my-task --browser`.
* **What limits it:** OpenShell decides which sites the browser can reach, the same way as for any other program. Any page the browser opens can receive data in its URL, so the list of sites is what keeps data in.
* **Local pages:** a dev server in the sandbox (`localhost`) works without a rule.
* **Don't** let the agent use your own Chrome.
* See [Headless browser use](docs/extras.md#headless-browser-use).

#### Logs and OpenTelemetry
* **What:** keep the sandboxes' security events (every allowed and denied connection, HTTP request and SSH session), or send them to a log backend, as OpenTelemetry logs.
* **How:** turn on OpenShell's structured log once, then export to a file or push to an OTLP endpoint, and look at the events with the small terminal viewer:
```bash
openshell settings set --global --key ocsf_json_enabled --value true --yes
bin/otel-export.py --out sandboxes.otlp.jsonl                          # to a file
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow   # live, to a collector
bin/otel-export.py --out - --follow | bin/otel-view.py                 # live, in the terminal
```
* **Careful where you send them:** the events show what the agent did (hosts, URLs, process names).
* See [Logging](docs/logging.md).

#### Viewing a web page in your browser
* **What:** [view a web page the agent serves](docs/working-in-sandboxes.md#viewing-a-web-page-from-the-sandbox) in your own browser.
* **How:** the agent runs a server on a port in the sandbox, and you forward the port:
```bash
openshell forward start 3000 my-task -d   # then open http://127.0.0.1:3000
openshell forward stop  3000 my-task
```
* **This adds risk:** the page is the agent's code, and in your browser it runs outside the sandbox, with your network access. It can reach other services on your machine, send data to any site, and use your browser's logins.
* **So:** only do it when you need to, and open the page in a private window.

If something fails, see [Troubleshooting](docs/troubleshooting.md).

## References
### OpenShell
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

### Podman
* [Podman](https://podman.io/)
* [Podman Desktop on macOS](https://podman-desktop.io/docs/installation/macos-install)

### Agents
* [OpenCode image](https://github.com/anomalyco/opencode/pkgs/container/opencode)
* [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
* [OpenRouter](https://openrouter.ai/)
