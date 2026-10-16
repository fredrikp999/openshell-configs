# Customizing
## Provider profiles
A profile is a YAML file that you write yourself or download, and then import into the gateway. No command generates it.
* **Ready-made profiles** are in the [OpenShell repo](https://github.com/NVIDIA/OpenShell/tree/main/providers). [providers/openrouter.yaml](../providers/openrouter.yaml) is a local copy of one.
* **Custom profiles** like [providers/claude-code-oauth.yaml](../providers/claude-code-oauth.yaml) are written by hand. That one is based on the upstream [claude-code.yaml](https://github.com/NVIDIA/OpenShell/blob/main/providers/claude-code.yaml), changed to use an OAuth token instead of an API key.

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
```yaml
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
```bash
openshell provider profile lint   -f providers/my-agent.yaml
openshell provider profile import -f providers/my-agent.yaml
openshell provider profile describe my-agent
```
4. Create a provider from it with `openshell provider create --type my-agent ...`

### Update a profile
`import` and `lint` fail once the profile exists (`custom provider profile '...' already exists`). Use `update` instead. It needs the current `resource_version` from the gateway, so the commands below read it and add it to a temporary copy of the file. Set `ID` to the profile's id, e.g. `claude-code-oauth` or `openrouter`:
```bash
ID=claude-code-oauth
V=$(openshell provider profile export $ID | awk '/^resource_version:/{print $2}')
sed "s/^id: $ID\$/&\nresource_version: $V/" providers/$ID.yaml > /tmp/$ID.yaml
openshell provider profile update $ID -f /tmp/$ID.yaml
openshell provider profile describe $ID
```
* Every provider of that type picks up the change; the provider records themselves aren't rewritten. Running sandboxes see the changed endpoints and binaries at their next sync, without a restart. A process that started earlier keeps the environment it started with, so start the agent again after changing a credential.

## Sandbox policies
What a sandbox may access comes from three places:
* **The policy file** (`--policy`) sets filesystem access. Without it, a sandbox gets OpenShell's built-in default.
* **The attached providers** add network access to the hosts in their profiles.
* **Network rules** you approve add more hosts, per sandbox.

### Filesystem policy
This repo has these policies: this one, [policies/example.yaml](../policies/example.yaml) (below), [policies/browser.yaml](../policies/browser.yaml) for the [browser](extras.md#headless-browser-use), [policies/hyperframes.yaml](../policies/hyperframes.yaml) for HyperFrames, [policies/artcraft.yaml](../policies/artcraft.yaml) for [VectorCraft and PhotoCraft](extras.md#artcraft-vectorcraft-and-photocraft) and [policies/antigravity.yaml](../policies/antigravity.yaml) for [Antigravity CLI](agents.md#antigravity-cli-with-a-google-account). The one used everywhere is [policies/vscode-terminal.yaml](../policies/vscode-terminal.yaml). It is the default policy plus `/dev/pts` and `/dev/ptmx`, so programs inside the sandbox can open terminals. VS Code's integrated terminal needs this; without it, it fails with `forkpty(3) failed`.
```yaml
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
* `landlock.compatibility` is `best_effort` by default: if the kernel can't enforce your filesystem rules, the sandbox still starts **without them** and logs a high-severity finding. `hard_requirement` makes it refuse to start instead. OpenShell also adds baseline paths itself (e.g. `/usr`, `/lib`, `/etc`, `/tmp`) when the policy has network rules, and always protects `/.openshell`.
* `include_workdir: true` makes the working directory (`/sandbox`, also `$HOME`) read-write.
* There is no `network_policies` section, so network access comes only from the attached providers and approved rules.

Create your own:
1. Start from [policies/example.yaml](../policies/example.yaml) (see [Example policy with network rules](#example-policy-with-network-rules)), or from the default policy of an existing sandbox. `--base` leaves out the provider's network rules, and the `sed` drops the header lines before the YAML:
```bash
openshell policy get claude-agent1 --base | sed -n '/^version:/,$p' > policies/my-policy.yaml
```
2. Edit the file, e.g. add paths to `read_only` or `read_write`. Only add what's needed: every path you add is something the agent can reach too.
3. Network rules that every sandbox needs can go in a `network_policies` section, as in the example below. For a provider's own hosts, prefer the profile's `endpoints`.

Use it:
* Pass it with `--policy policies/my-policy.yaml` when you create the sandbox.
* Check what the sandbox got: `openshell policy get claude-agent1 --base`, or `--full` to include the provider's network rules.
* **Filesystem changes need a new sandbox.** Filesystem rules are fixed when the sandbox starts. `openshell policy set` on a running sandbox loads the new version, but processes still can't access the new paths. Delete the sandbox and create it again with `--policy`.
* **Network changes apply right away.** `openshell policy set <sandbox> --policy <file> --wait` hot-reloads `network_policies` without recreating the sandbox. `policy set` replaces the whole base policy, so start from `openshell policy get <sandbox> --base` and keep its filesystem part unchanged. Connections that were open under the old rules (keep-alive, tunnels, WebSockets) are closed, so clients have to reconnect. Without `--wait`, success only means the gateway accepted the change; with `--wait`, exit code 0 means the sandbox loaded it, 1 that it rejected it and 124 that the wait timed out. Removing paths or changing `include_workdir`, `landlock` or `process` is rejected on a running sandbox. If a new version can't be loaded, the sandbox blocks traffic until a valid policy loads (`policy_validation_failure_mode`, default `fail_closed`).

### Example policy with network rules
[policies/example.yaml](../policies/example.yaml) is the terminal policy plus five network rules, as a starting point for your own policies. The paths are for the `claude-sandbox` image.

| Rule | Allows | Blocks |
|---|---|---|
| `python_docs` | Claude Code (`claude.exe`) reading `docs.python.org`, e.g. with its WebFetch tool | Other programs, and anything but GET/HEAD/OPTIONS (`access: read-only`) |
| `npm_registry` | `node` (which runs npm) downloading packages from `registry.npmjs.org` | Writes such as `npm login` or `npm publish` |
| `github_clone` | `git clone` and `fetch` from GitHub, via git's HTTPS helper `git-remote-http` | `git push` (explicit `deny_rules`), and other git hosts |
| `context7_mcp` | Claude Code using the Context7 MCP server (library docs): connecting, listing tools, and the tools `resolve-library-id` and `query-docs` | Every other MCP method and tool |
| `huggingface_mcp` | Claude Code using the Hugging Face MCP server: all standard MCP methods, and tools matching `hub_repo_*` | Other tools, and `hf_fs` explicitly (`deny_rules`) |

The structure of a rule:
```yaml
network_policies:
  npm_registry:                    # rule name (any)
    name: npm-registry
    endpoints:                     # where to
      - host: registry.npmjs.org
        port: 443
        protocol: rest             # inspect each HTTP request...
        access: read-only          # ...and allow only GET, HEAD and OPTIONS
        enforcement: enforce       # block violations (the default, audit, only logs them)
    binaries:                      # who may connect
      - path: /usr/local/bin/node
```
* **Binaries:** list the program that actually opens the connection, by its real path (check with `readlink -f` inside the sandbox). For npm that's `node`, and for git over HTTPS it's `/usr/lib/git-core/git-remote-http`. The `DENIED` lines in `openshell logs <sandbox>` show the path OpenShell saw. Globs work (`/usr/lib/jvm/*/bin/java`), and for a script you list its interpreter. OpenShell records a hash of each program the first time it connects, and denies it from then on if the file changes, e.g. after an upgrade inside the sandbox.
* **`access` or `rules`:** `access` is a preset (`read-only`, `read-write`, `full`). `rules` allow specific methods, paths and query parameters, as in `github_clone`. An endpoint uses one or the other.
* **`deny_rules`** always win over allow rules. Use them to make a ban explicit.
* **`enforcement` defaults to `audit`**, which only logs a request that breaks the rules and lets it through. Set `enforce` to block it, as the examples here do. It only applies to the checks of `protocol: rest`/`mcp` endpoints; a connection to a host or binary no rule allows is always denied.
* **Some destinations are never allowed by a rule:** loopback and link-local addresses (including the cloud metadata address 169.254.169.254), and, on exact-host and IP endpoints, the ports 2379, 2380, 6443, 10250 and 10255. Wildcard and host-less endpoints reach private addresses only through `allowed_ips`.
* **Without `protocol`**, OpenShell only checks host, port and binary, and allows any request.
* **Credentials:** a network rule never sends provider credentials. Those only go to the hosts in the provider's profile.

**Remote MCP servers** (`context7_mcp`, `huggingface_mcp`) use `protocol: mcp`. OpenShell then reads every MCP request and checks the method and, for `tools/call`, the tool name:
```yaml
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
* **`mcp.versions`:** the default is only `2025-11-25` (accepted: `2025-03-26`, `2025-06-18`, `2025-11-25` and `2026-07-28`). Clients send `initialize` without a version header, which counts as `2025-03-26`, so list that too.
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

Use it as-is or copy and edit it:
```bash
cp policies/example.yaml policies/my-task.yaml
openshell sandbox create --name my-task --from claude-sandbox:latest --provider claude \
  --policy policies/my-task.yaml --detach -- sleep infinity
```

### Network rules
A sandbox starts out mostly locked down. When the agent or another tool tries to reach a host that isn't allowed, the connection is denied and logged, and OpenShell proposes a rule that would allow it. Ask the agent to do what you want to allow (e.g. fetch a web page), then review the proposals. The examples use `opencode-agent1`.

* Check the logs:
```bash
openshell logs opencode-agent1
openshell logs opencode-agent1 | grep DENIED
```
   Or watch them live, for all sandboxes, with `bin/watch-denied.sh` (see [Watching denials](logging.md#watching-denials)).

* List the pending proposals:
```bash
openshell rule get opencode-agent1 --status pending
```

* Approve a proposal:
```bash
openshell rule approve opencode-agent1 --chunk-id <chunk-id>
```
```
OK Chunk approved. Policy version: 2, hash: 896a5bc27d1f
```

* Or reject it, with a reason:
```bash
openshell rule reject opencode-agent1 \
  --chunk-id <chunk-id> \
  --reason "Not needed for this task."
```
```
OK Chunk rejected.
```

* View the policy versions:
```bash
openshell policy list opencode-agent1
```
```
VERSION  HASH           STATUS       CREATED                  ERROR
3        af2b9e891d51   Loaded       1791622741186
2        896a5bc27d1f   Superseded   1791622467183
1        a45a8ff3564f   Superseded   1791621734038
```

* View the approved rules:
```bash
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
* **Every proposal is checked** by OpenShell's policy prover before you see it. It flags risky reach: a provider credential going to a new host or port, a new HTTP method where a credential applies, uninspectable traffic (`git`, `ssh`, `nc`) to a credentialed host, and link-local or cloud-metadata addresses. `openshell rule approve-all <sandbox>` skips the flagged ones unless you add `--include-security-flagged`.
* **Auto-approval is off by default.** `proposal_approval_mode=auto` (global, per sandbox or `--approval-mode auto` at creation) approves only proposals with no findings and no flagged destination (private IPs, wildcards, ports above 49152, database ports such as 5432). An agent can only propose rules itself, through `policy.local`, after `openshell settings set --global --key agent_policy_proposals_enabled --value true --yes`. While a global policy is active, no proposal can be approved.
