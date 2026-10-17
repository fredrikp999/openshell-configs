# Extras: MCP servers, ACP, a headless browser, HyperFrames, VectorCraft and PhotoCraft
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
* **All images:** every image has its agent's ACP command, because the variants are built on the base images: `claude-browser` and `claude-hyperframes` have `claude-acp-start`, and `agy-hyperframes`, `agy-node` and `agy-python` have `agy-acp-start` (`agy-hyperframes` and `claude-hyperframes` run `hyperframes-init` first; `agy-hyperframes` also registers Playwright MCP). `--acp` works with `--browser`, `--hyperframes`, `--node` and `--python`. `agy-hyperframes` also contains Claude's command, so `acp_client.py` takes it for `agy`.
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
`bin/sandbox.sh agy my-video --hyperframes --forward 3102` does the same with `agy` instead of Claude Code, using the `agy-hyperframes` image (built on `claude-hyperframes`, plus `agy` and the ACP adapter) and [policies/agy-hyperframes.yaml](../policies/agy-hyperframes.yaml). Playwright MCP is registered with `agy` on first start, so it can use the headless browser. The skills are still copied to `~/.claude/skills`, where `agy` doesn't look for them. Because `agy`'s login tokens sit in the sandbox, read the warning in [agents.md](agents.md#antigravity-cli-with-a-google-account) first.

### Things to watch for
* **Port in use on your machine:** `openshell forward` uses the same port number on both sides, and `--forward` fails if the port is taken (`lsof -i :3102`). HyperFrames' default preview port 3002 is often in use if you also run HyperFrames on the host, so pick another, as above.
* **The Studio runs the agent's code in your browser**, outside the sandbox. See [Viewing a web page from the sandbox](working-in-sandboxes.md#viewing-a-web-page-from-the-sandbox). Use a private window.
* **`hyperframes catalog` stalls in the sandbox.** It fetches hundreds of registry files from `raw.githubusercontent.com`. OpenShell maps each allowed host to a short-lived internal address, and Node keeps reusing connections after that mapping expires, so they're denied (`transparent TCP mapping is expired` in `openshell logs`) and the command hangs. While it runs, other HyperFrames commands in the sandbox may hang too, so stop it. `hyperframes add <name>` works, so browse the catalog at [hyperframes.heygen.com](https://hyperframes.heygen.com) and tell the agent which block to add.
* **Not included:** local transcription (whisper.cpp), local voice (Kokoro) and music (MusicGen) models, and HeyGen's cloud features (avatars, TTS, cloud rendering), which need a HeyGen API key and `api.heygen.com`. `npx hyperframes doctor` lists what's missing; Docker, `/dev/shm` size and these optional models show as failed and don't matter for rendering.
* **Rendering uses software GL**, so it's slower than on a Mac with a GPU: about 1.5 s of render time per second of video for a simple composition.
* **`npx` contacts registry.npmjs.org** once, which shows as DENIED. HyperFrames is installed globally, so it works anyway.
* **Size:** the image adds about 0.5 GB to `claude-browser` (2.3 GB in all).
* **Test:** [tests/hyperframes/run.sh](../tests/hyperframes/run.sh) creates a sandbox, renders a project, checks that `hyperframes check` loads GSAP without errors, and that the preview is reachable from your machine through a forwarded port. `--claude` also has Claude Code make and render a short video.

## ArtCraft: VectorCraft and PhotoCraft
[VectorCraft](https://getartcraft.com/apps/vectorcraft) is an open-source vector editor for SVG and PDF, and [PhotoCraft](https://getartcraft.com/apps/photocraft) an open-source photo editor (layers, adjustments, filters, PSD, PNG, JPEG and more). Both are written in Rust (MIT or Apache-2.0, by the ArtCraft team), and both have a headless command-line tool with an MCP server, so Claude can draw, edit and export in the sandbox. The `claude-artcraft` image has both CLIs and registers both servers.

### Set it up
1. **Build the image.** It builds on `claude-sandbox`; `make` builds both in order:
```bash
make claude-artcraft
```
   Or by hand:
```bash
podman build -t claude-sandbox:latest   images/claude-sandbox
podman build -t claude-artcraft:latest  images/claude-artcraft
```
2. **Create the sandbox.** `--artcraft` uses the image and [policies/artcraft.yaml](../policies/artcraft.yaml):
```bash
bin/sandbox.sh claude my-art --artcraft
```
   This also forwards port 3102 for the gallery (step 5). If that port is in use on your machine (e.g. by a HyperFrames sandbox), it only warns and goes on; `--forward PORT` forwards another port, and then the gallery must run on it too (`artcraft-gallery --port PORT`).
3. **Upload what Claude should work on** (photos, a PSD), if any:
```bash
openshell sandbox upload my-art ./raw /sandbox
```
4. **Ask Claude**, e.g. "Draw a 1200x630 social card for our CLI with VectorCraft and export card.svg" or "Grade the photos in /sandbox/raw with PhotoCraft (a little more contrast, sharpen) and write them to /sandbox/graded."
5. **Browse the images in your browser:** open http://127.0.0.1:3102. The gallery starts by itself with the agent. See [The gallery](#the-gallery) below.
6. **Get the files out:**
```bash
openshell sandbox download my-art /sandbox/graded .
```

By hand, without the script:
```bash
openshell sandbox create --name my-art --from claude-artcraft:latest --provider claude \
  --policy policies/artcraft.yaml --detach -- sleep infinity
openshell sandbox exec my-art --workdir /sandbox -- claude-start
```
`--artcraft` is only for Claude, and can't be combined with `--browser` or `--hyperframes`. `--acp` and `--vscode` work with it.

### What the image adds
[images/claude-artcraft](../images/claude-artcraft) builds on `claude-sandbox`. It adds:
* **`vectorcraft-cli` and `photocraft-cli`**, the headless tools from each app's release for the image's architecture (arm64 or x86_64), pinned with `ARG VECTORCRAFT_VERSION` and `ARG PHOTOCRAFT_VERSION` and checked against the release's `SHA256SUMS.txt` during the build. The desktop apps from the same releases are left out, because the sandbox has no display. The build fetches them from GitHub, so it needs network access on your machine, but the sandbox doesn't.
* **The MCP servers**, registered as `vectorcraft` and `photocraft` in [claude-start.json](../images/claude-artcraft/claude-start.json), which `claude-start` copies to `~/.claude.json` on first start. Each runs `<app>-cli mcp --automation-read-root /sandbox --automation-write-root /sandbox`, so the servers can only open and save files below `/sandbox`.
* **The skill `clean-vector-from-raster`** ([images/claude-artcraft/skills](../images/claude-artcraft/skills/clean-vector-from-raster/SKILL.md)): a workflow for turning a raster illustration (e.g. one figure from a sprite sheet on a chroma-key background) into a clean, print-ready SVG: prepare the image in PhotoCraft (crop, upscale, smooth), trace it in VectorCraft, simplify and export. Ask for it by name or describe the task. It is copied to `~/.claude/skills` on first start by **`artcraft-init`**, which `claude-start` and `claude-acp-start` run (a skill that is already there isn't overwritten, so edits in a sandbox stay). To add a skill, put its folder in `images/claude-artcraft/skills/` and rebuild.
* **`artcraft-key`**, a command (on the `PATH`) for the chroma-key cleanup in the `clean-vector-from-raster` workflow: `artcraft-key bg FILE.png` shows a PNG's background color and whether the rule removes it, `key` makes the background transparent (`NAME_rgb.png` gives `NAME_key.png`, never overwriting the input), `check` counts the background pixels left (exit status 1 if there are any) and `strip FILE.svg` removes paths filled with the background color from a traced SVG. The default background is magenta, as **spill**: `min(r, b) - g >= 30` and `min(r, b) >= 110`, which catches `#ff00ff`, lighter magentas such as `#fc3efb` and the blended edges, and leaves dark hair and outlines. For another background give `--color "#00ff00" --tolerance 50` (each of r, g, b may differ by that much) or `--range "0-90,170-255,0-90"`; `bg` prints the command to use. It uses numpy and Pillow when they are installed (`uv venv && uv pip install numpy pillow`, then run it with that Python: `.venv/bin/python /usr/local/bin/artcraft-key ...`; faster, any PNG type), else its own reader for 8-bit RGB/RGBA PNGs; both give the same output. [images/claude-artcraft/artcraft-key](../images/claude-artcraft/artcraft-key), `artcraft-key --help`, and [tests/artcraft-key/run.sh](../tests/artcraft-key/run.sh), which needs no sandbox.
* **Python 3** from Debian with pip and venv, and **uv** ([docs.astral.sh/uv](https://docs.astral.sh/uv/), pinned with `ARG UV_VERSION`, checked against its `.sha256`). Debian's pip refuses system-wide installs, so the agent makes a virtual environment: `uv venv && uv pip install pillow`, or `python3 -m venv .venv && .venv/bin/pip install pillow`. `uvx` runs tools without installing them. **Wheels only** (see [Installing Python packages](#installing-python-packages) below). `UV_PYTHON_DOWNLOADS=never` makes uv use the Debian Python, because the policy only allows PyPI and uv would otherwise fetch a Python from GitHub.
* **`artcraft-gallery`**, a small web server (Python standard library) that shows the images in a folder. See below.
* **Each app's docs and licences** in `/usr/local/share/doc/vectorcraft` and `/usr/local/share/doc/photocraft` (the READMEs describe the command API).

The CLIs also work without MCP, e.g. `vectorcraft-cli run --in art.vectorcraft --export art.pdf`, or `photocraft-cli convert in.psd out.png`, `photocraft-cli run` for a list of engine commands and `photocraft-cli batch` for a folder of images. `--help` lists the rest. Both apps are in active development, so commands may change between releases.

### The gallery
`artcraft-gallery [--dir /sandbox] [--port 3102] [--host 127.0.0.1] [--background]` serves a page with a grid of thumbnails of the images below `--dir` (PNG, JPEG, GIF, WebP, SVG, AVIF, BMP, TIFF), newest first. It checks for new files every three seconds, so images appear as Claude writes them. You can filter by name and folder, sort by date, name or size, and click an image for a large view (arrow keys move between images, Esc closes) or to open the original.
* **It starts by itself.** `claude-start` and `claude-acp-start` (through `artcraft-init`) run `artcraft-gallery --background`, which detaches, logs to `/tmp/artcraft-gallery.log` and does nothing if the port is already in use, so it keeps running after the agent quits and a second start doesn't make a second server. It starts when the agent starts, not when the sandbox is created, so with `--vscode` or a plain `sandbox exec` start it yourself (`artcraft-gallery --background`). To use another port or folder, run `artcraft-gallery --port N --dir D` yourself.
* **Opening it:** you reach it through a port forward, which `bin/sandbox.sh claude my-art --artcraft` starts for 3102 every time you run it (or `openshell forward start 3102 my-art -d` by hand). The forward goes through the gateway, so the sandbox opens no port and needs no network rule. Then open http://127.0.0.1:3102. Ask Claude to put its results in `/sandbox`, in folders if you like; the folder menu follows them.
* **Read-only:** GET only, and only image files below `--dir`. Hidden folders (`.claude`, `.venv` and the like), `node_modules` and any other file type, such as `.claude.json`, give 404, and so does a path that leaves `--dir`. Files are sent with `Content-Security-Policy: sandbox`, so scripts in an SVG don't run if you open one directly.
* **Binding:** it listens on `127.0.0.1` in the sandbox, which is what the forward connects to. Don't use `--host 0.0.0.0` unless you know why.
* **PDFs and PSDs** aren't shown, because browsers don't render them as images. Ask Claude to export PNG or SVG next to them.
* **Source:** [images/claude-artcraft/artcraft-gallery](../images/claude-artcraft/artcraft-gallery), one Python file; change it and rebuild the image to customize the page.

### Installing Python packages
The policy lets `python3` and `uv` reach PyPI, so the agent can install packages. Nothing can make an installed package safe; the image and these habits limit what a bad one can do.

**Wheels and source distributions.** PyPI holds two kinds of files. A *wheel* (`.whl`) is prebuilt: installing it only unpacks files, and no package code runs. A *source distribution* (`.tar.gz`) has to be built first, which runs the package's own build code (`setup.py` or a build backend) at install time, with the agent's rights, before you have used the package. Popular packages publish wheels; others only have the source file.

**The image installs wheels only.** `PIP_ONLY_BINARY=:all:` is set for pip, and [uv.toml](../images/claude-artcraft/uv.toml) in `/etc/uv/uv.toml` sets `no-build = true` for uv, for `uv pip`, `uv add`, `uv sync` and `uvx`. (uv's `UV_NO_BUILD` variable would not do it: `uv pip` ignores it, so the image uses the config file.) A package with only a source file then fails with a message such as "Wheels are required for `x` because building from source is disabled". The agent can't edit `/etc`, but it can still switch the setting off for one command (`uv --no-config pip install x`, `PIP_ONLY_BINARY= pip install x`), as it can run any command in its sandbox. So this guards against accidents and sloppy installs, not against an agent set on building; the network rules are the limit. A wheel can still run code when it is imported.

**Other ways to lower the risk:**
* **Ignore new releases:** `uv pip install --exclude-newer 2026-10-01 pillow` skips everything uploaded after that date. Malicious releases are mostly found and removed within days, so a hijacked fresh release can't reach you.
* **Pin and check hashes:** a requirements file with exact versions and hashes, installed with `uv pip install --require-hashes -r requirements.txt` (or `pip install --require-hashes`), rejects any file that differs from what you reviewed.
* **Choose well-known packages.** Check the name (typosquats like `pilllow`), the maintainers and source repo on pypi.org, and the release history (a package made last week with one release is suspect). Popular packages are reviewed by many people, but they do get compromised now and then. [OSV.dev](https://osv.dev) lists known vulnerabilities and malware reports, `pip-audit` checks an environment against it, and [deps.dev](https://deps.dev) shows dependency trees.
* **Allow only the packages you approve** (optional). Every install starts with a request to `https://pypi.org/simple/<name>/`, the package's index page (PEP 503) with links to its files, so a path rule on `pypi.org` can limit which packages the installer finds, by replacing `access: read-only` with rules like these (one per package *and* each of its dependencies; names are lowercase with hyphens, e.g. `typing-extensions`):
```yaml
      - host: pypi.org
        port: 443
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET, path: "/simple/pillow/" }
          - allow: { method: GET, path: "/simple/numpy/" }
```
  The files themselves come from `files.pythonhosted.org`, whose paths hold only hashes and no package names, so that host can't be limited by package. The installer can't find other packages, but someone who knows a file's exact URL could still fetch it. This lowers the risk without removing it. Test the list in a sandbox before relying on it: a dependency you forgot fails the install, which is how you find it.
* **Remove the `pypi` rule** from a copy of the policy for tasks that need no packages.

### The policy
[policies/artcraft.yaml](../policies/artcraft.yaml) is the terminal policy ([vscode-terminal.yaml](../policies/vscode-terminal.yaml)) plus one network rule: read-only (GET) access to PyPI, `pypi.org` and `files.pythonhosted.org`, for `/usr/bin/python3` (which also covers pip) and `/usr/local/bin/uv` and `uvx`. Both apps work on local files and need nothing else. Claude Code reaches its API through the provider, as in the other images. Any other host, e.g. `example.com` or a GitHub download, is denied.

A GET to PyPI can carry data in its URL, and the setup scripts of a package the agent installs run with its rights, so this is less locked down than a policy without the rule. If the task needs no packages, delete the `pypi` rule from a copy of the policy. To add hosts (fonts or images to fetch), add rules and apply them to the running sandbox with `openshell policy set my-art --policy policies/artcraft.yaml --wait`. See [Sandbox policies](customizing.md#sandbox-policies).

### Things to watch for
* **Gallery shows nothing or the page doesn't load?** The forward is on (`openshell forward list`) but nothing listens in the sandbox if it was created from an older image or the agent hasn't started: check with `openshell sandbox exec my-art -- python3 -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:3102/api/files').read())"` and read `/tmp/artcraft-gallery.log`. An empty page with "No images yet." means the server works and `/sandbox` has no images (images in hidden folders or other file types aren't shown).
* **Claude Code only.** There is no `agy` or OpenCode variant.
* **The MCP root is `/sandbox`.** Files elsewhere (e.g. `/tmp`) can't be opened or saved by the servers. The agent's other tools aren't limited by it, but by the sandbox's filesystem policy.
* **Existing sandboxes** keep their old image. Create a new one after rebuilding, e.g. to update a version.
* **Size:** the two CLI binaries are about 90 MB each, plus Python and uv.
* **Wheels only.** A package with no wheel for arm64 or x86_64 and Debian's Python 3.11 can't be installed; see [Installing Python packages](#installing-python-packages).
* **Only PyPI.** `npm`, `git clone` from GitHub and other downloads are denied. A package that downloads something else when it installs or runs (a model, a binary) fails the same way.
