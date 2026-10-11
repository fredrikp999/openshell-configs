# Working in sandboxes
The examples use `claude-agent1`. Everything works the same for the OpenCode sandboxes.

## Start and use a sandbox
Create a sandbox once, then use it as often as you like: with the agent in your terminal, with VS Code, or both. The sandbox runs `sleep infinity` as its main process, so it keeps running when you quit the agent or close VS Code, and the files stay.

You can do this by hand or with [bin/sandbox.sh](../bin/sandbox.sh). The values per agent:

| Agent | Image | Provider | Agent command | ACP command |
|---|---|---|---|---|
| Claude Code | `claude-sandbox:latest` | `claude` | `claude-start` | `claude-acp-start` |
| OpenCode | `opencode-sandbox:latest` | `openrouter` | `opencode -m openrouter/nvidia/nemotron-3.5-lightning:free` | `opencode acp` |

The examples below use Claude and the sandbox name `my-task`.

### By hand
1. **Create the sandbox** (once):
```bash
openshell sandbox create \
  --name my-task \
  --from claude-sandbox:latest \
  --provider claude \
  --policy policies/vscode-terminal.yaml \
  --detach \
  -- sleep infinity
```
* `--detach` returns right away and leaves `sleep infinity` running in the background.
* `--policy` adds terminal access, which VS Code's terminal needs (see [Filesystem policy](customizing.md#filesystem-policy)).
* Wait until `openshell sandbox list` shows `my-task` as `Ready`.

2. **Use the agent in your terminal:**
```bash
openshell sandbox exec my-task --workdir /sandbox -- claude-start
```
* `--workdir` is the folder the agent starts in, e.g. `/sandbox/myrepo`.
* Arguments after the agent command go to the agent, e.g. `... -- claude-start -p 'reply with OK'` as a smoke test.
* Quit the agent as usual. The sandbox keeps running.

3. **Or use VS Code:**
```bash
openshell sandbox connect my-task --editor vscode
```
* VS Code opens a window connected to the sandbox. Open a folder with *File > Open Folder*, and start the agent in *Terminal > New Terminal* with `claude-start`.
* See [VS Code](#vs-code) for the one-time setup.

4. **Or open a shell in the sandbox** to look around or run commands:
```bash
openshell sandbox exec my-task --workdir /sandbox -- bash
```
* Leave the shell with `exit` or Ctrl-D. The sandbox keeps running.
* The shell has the same restrictions as the agent, and the provider's credentials as placeholders, so you can start `claude-start` or `opencode` from it too.
* **A single command, no shell:**
```bash
openshell sandbox exec my-task -- ls -la /sandbox
```
* **Plain SSH:** after you've connected a sandbox once with `--editor vscode`, it has an SSH host entry (`openshell-<name>.default`), so this works:
```bash
ssh openshell-my-task.default
```
For other sandboxes, add the entry first:
```bash
openshell sandbox ssh-config my-task >> ~/.ssh/config
```
The entry tunnels SSH through the gateway with `openshell ssh-proxy`, so the sandbox doesn't need an open port. `scp` doesn't work over this connection and the images have no `rsync`. To copy files, use `openshell sandbox upload` and `download` (see [Getting code in and out](#getting-code-in-and-out)).

5. **Later:** check that the sandbox is still running, and use it again with step 2, 3 or 4:
```bash
openshell sandbox list
```
* `Ready`: running, use it.
* `Completed` or `Error`: stopped. Delete it and create it again (step 1). Files in it are lost, so get your work out first (see [Getting code in and out](#getting-code-in-and-out)).

6. **When the task is done:**
```bash
openshell sandbox delete my-task
```

### With the script
[bin/sandbox.sh](../bin/sandbox.sh) does steps 1 to 3 in one command. It creates the sandbox on first use and reuses it after that:
```bash
bin/sandbox.sh <claude|opencode> [name] [--vscode|--acp] [--browser] [--workdir DIR] [-- agent args...]
```
| Command | What happens |
|---|---|
| `bin/sandbox.sh claude` | Claude in this terminal, in sandbox `claude-agent1` |
| `bin/sandbox.sh claude my-task` | Claude in this terminal, in sandbox `my-task` |
| `bin/sandbox.sh claude my-task --vscode` | Opens sandbox `my-task` in VS Code; start Claude in its terminal |
| `bin/sandbox.sh opencode` | OpenCode in this terminal, in sandbox `opencode-agent1` |
| `bin/sandbox.sh claude my-task -w /sandbox/myrepo` | Claude starts in `/sandbox/myrepo` |
| `bin/sandbox.sh claude my-task -- -p 'reply with OK'` | Passes arguments to the agent (here: a non-interactive smoke test) |
| `bin/sandbox.sh opencode my-task --acp` | Runs OpenCode's ACP server on stdin/stdout, for a UI (see [ACP](extras.md#acp-agent-client-protocol)) |
| `bin/sandbox.sh claude my-task --acp` | The same for Claude Code, through the ACP adapter |
| `bin/sandbox.sh claude my-task --browser` | Claude with a headless browser: image `claude-browser`, policy [policies/browser.yaml](../policies/browser.yaml) (see [Browser](extras.md#headless-browser-use)). Only matters when the sandbox is created |

* The script uses the image, provider and agent command from the table above. Set the OpenCode model with `OPENCODE_MODEL=...`.
* **Requirements:** the provider and image from the agent's chapter must exist.
* **A stopped sandbox** (`Completed` or `Error`) isn't reused. The script says so; delete it with `openshell sandbox delete <name>` and run the script again.
* For a shell, checking status and deleting, use steps 4 to 6 above.

## VS Code
VS Code connects to a sandbox over SSH with the Remote-SSH extension. OpenShell tunnels the SSH connection through the gateway, so the sandbox doesn't expose any port.

### One-time setup
* Install the [Remote-SSH](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-ssh) extension, and make sure the `code` command works in a terminal (in VS Code: *Shell Command: Install 'code' command in PATH*).
* Add this to your VS Code user settings (`settings.json`):
```json
"remote.SSH.localServerDownload": "always",
```
VS Code installs "VS Code Server" in the sandbox on first connect. By default the sandbox downloads it itself, which fails because the sandbox can't reach Microsoft's servers. With this setting, your machine downloads it and copies it in over SSH.

### Connect
The sandbox must be running (`Ready` in `openshell sandbox list`) and created with `--policy policies/vscode-terminal.yaml`, otherwise VS Code's terminal won't start.
```bash
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

### Single files
For a file that isn't code in a repo (a spec, a data file, a screenshot or report the agent made), copy it with `upload` and `download`. Give a folder as the destination. The file lands in it under its own name:
```bash
# into the sandbox: ./spec.md -> /sandbox/spec.md
openshell sandbox upload my-task ./spec.md /sandbox

# out of the sandbox: /sandbox/myrepo/report.html -> ./report.html
openshell sandbox download my-task /sandbox/myrepo/report.html .
```
* **Files git ignores aren't uploaded.** Inside a git repo, `upload` applies `.gitignore`, so e.g. a `.env` or a build output is left out. A file outside any repo is uploaded as is (the CLI warns that it uploads "without Git filtering").
* **`scp` and `rsync` don't work** over the sandbox's SSH connection (see [Start and use a sandbox](#start-and-use-a-sandbox)). Use `upload` and `download`.
* **Check what comes out** before you open or run it. A file the agent wrote is untrusted, like its code.
* **Keep secrets out.** Anything you upload is readable by the agent and can end up with the model provider.

### 1. Git bundles in and out (recommended)
A git bundle is a single file that contains commits, like a portable remote. The sandbox never gets git credentials or network access to your git host, and you review everything before it leaves your machine.

#### With the script
[bin/bundle.sh](../bin/bundle.sh) does the steps below in two commands:
```bash
bin/bundle.sh in  <sandbox> <repo> [--branch NAME] [--base BRANCH]
bin/bundle.sh out <sandbox> <repo> [--branch NAME] [--base BRANCH] [--force]
```
A typical task, with the sandbox `my-task` and the repo `./myrepo`:
```bash
bin/bundle.sh in my-task ./myrepo
# the agent works in /sandbox/myrepo and commits on branch agent/my-task
bin/bundle.sh out my-task ./myrepo
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
```bash
git -C ./myrepo bundle create ../in.bundle --all
openshell sandbox upload claude-agent1 ./in.bundle /sandbox
```

* Clone it inside the sandbox on a work branch, e.g. ask the agent to do it, or run:
```bash
openshell sandbox exec claude-agent1 -- sh -c '
  git clone -q /sandbox/in.bundle /sandbox/myrepo &&
  cd /sandbox/myrepo &&
  git config user.name "Claude (sandbox)" &&
  git config user.email "claude@sandbox.local" &&
  git checkout -b agent/my-task'
```

* Let the agent work and commit on `agent/my-task`. Then pack the new commits and download them:
```bash
openshell sandbox exec claude-agent1 -- \
  git -C /sandbox/myrepo bundle create /sandbox/out.bundle main..agent/my-task
openshell sandbox download claude-agent1 /sandbox/out.bundle .
```

* Fetch the branch into your repo, review it, then push and open the MR yourself:
```bash
git -C ./myrepo fetch ../out.bundle agent/my-task:agent/my-task
git -C ./myrepo log --oneline main..agent/my-task
git -C ./myrepo diff main agent/my-task
git -C ./myrepo push origin agent/my-task
```

* To give the sandbox newer commits from `main`, create a new `in.bundle`, upload it again, and run `git fetch /sandbox/in.bundle main:main` inside the sandbox.

### 2. Read-only clone in the sandbox
Attach a git provider that only allows reads, so the agent can clone and fetch by itself. Get the results out with a bundle as in approach 1. The upstream [github.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/github.yaml) profile works this way: it allows clone and fetch, but not push.
```bash
openshell provider profile import --url https://raw.githubusercontent.com/NVIDIA/OpenShell/main/providers/github.yaml
GITHUB_TOKEN=<read-only-token> openshell provider create --name github-ro --type github --from-existing
openshell sandbox create ... --provider claude --provider github-ro ...
```
* There is no upstream GitLab profile. For GitLab, write your own for your GitLab host (see [Provider profiles](customizing.md#provider-profiles)).

### 3. Push from inside the sandbox
Possible, but a sandbox that can push can also send your code anywhere the token reaches. Only do this when you trust the setup, and limit it:
* Use a token limited to one repository (e.g. a GitHub fine-grained token or a GitLab project access token).
* Allow pushes (`git-receive-pack`) for that one repository only, with a policy applied by `openshell policy set`. The official [GitHub Push Access tutorial](https://docs.nvidia.com/openshell/tutorials/github-push-access) shows the exact policy.
* Protect `main` on the git server. The policy can limit which repository, but not which branch.
* Opening the MR or PR from inside also needs `gh` or `glab` in the image, and API access to that repository in the policy.

## Viewing a web page from the sandbox
To see and click through a page the agent builds, the agent serves it on a port in the sandbox, and OpenShell forwards that port to your machine. The forward goes through the gateway (over SSH, like VS Code), so the sandbox opens no port and no network rule is needed.

1. **Ask the agent to serve the page** on a port, in the background, e.g. "serve the page on port 3000". A small server in Node.js (which the Claude image has; it has no Python) needs nothing else. A dev server like `npx vite` must first be installed from npm, which needs the `npm_registry` rule from [policies/example.yaml](../policies/example.yaml). Binding to `127.0.0.1` in the sandbox is enough.
2. **Forward the port** on your machine:
```bash
openshell forward start 3000 my-task -d
```
```
✓ Forwarding port 3000 to sandbox my-task in the background
  Access at: http://127.0.0.1:3000/
  Stop with: openshell forward stop 3000 my-task
```
3. **Open http://127.0.0.1:3000.** With a dev server that reloads on changes, you see the agent's edits right away.
4. **List and stop forwards:**
```bash
openshell forward list
openshell forward stop 3000 my-task
```

* **Without `-d`** the forward runs in the foreground until Ctrl-C.
* **Bound to `127.0.0.1` on your machine** by default, so others on your network can't reach it. `openshell forward start 0.0.0.0:3000 ...` would open it to them; don't.
* **One forward per local port.** A second `forward start` on the same port fails with `Port 3000 is already forwarded`. Stop the old one first, or use another port.
* **The page runs outside the sandbox.** In your browser, the agent's code has your network access, not the sandbox's: it can call other services on your `localhost` (e.g. an [MCP server on the host](extras.md#mcp-servers-in-containers-on-the-host)), send data to any site, and use whatever your browser is logged into. Open it in a private window or a separate browser profile without logins, and treat it like the agent's other code until you've reviewed it.
* **Alternatives:** VS Code forwards ports itself when connected with `--editor vscode` (see its *Ports* tab). For one static page, [download it](#single-files) and open the file. `openshell service expose` publishes a service through the gateway under its own URL, which is more than viewing it yourself needs.
* **For the agent itself** to look at the page, use the [browser](extras.md#headless-browser-use) in the sandbox instead. It reaches `localhost` there without any forward.

## Many sandboxes in parallel
* **One sandbox per task or branch**, named after the task (`claude-auth-fix`, `claude-docs`). Each has its own filesystem, policy and approved rules, so agents don't interfere with each other.
* **Providers are shared** - create a provider once and attach it to every sandbox with `--provider`.
* **Labels** - add e.g. `--label project=foo --label task=auth` on create, then list with `openshell sandbox list --selector project=foo`.
* **Templates** - store the image and resources once, then create sandboxes from it. `--template` can't be combined with `--from`, `--cpu`, `--memory` or `--env`:
```bash
openshell sandbox template create claude --image claude-sandbox:latest --cpu 2 --memory 4Gi
openshell sandbox create --name claude-auth-fix --template claude --provider claude \
  --policy policies/vscode-terminal.yaml --detach -- sleep infinity
```
* **Resources** - all sandboxes run inside the one Podman machine. Give it room if you run several:
```bash
podman machine stop
podman machine set --cpus 6 --memory 12288
podman machine start
```
* **Usage limits** - parallel Claude sessions share your Claude subscription's limits.
* **Approved rules are per sandbox** and reset when the sandbox is recreated. Hosts every sandbox needs belong in the profile or in a policy file.
* **Overview and cleanup** - `openshell sandbox list`, and `openshell sandbox delete <sandbox>` when a task is done.
