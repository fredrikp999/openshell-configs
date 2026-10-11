# Setup
## Podman
OpenShell runs the sandboxes in a container runtime. These steps use Podman (5.x is required). OpenShell can also use Docker (28.0 or later) or MicroVMs.

### macOS (Apple Silicon)
On macOS, Podman runs containers in a Linux VM called a Podman machine.

* Install Podman, either with the installer from [podman.io](https://podman.io/) (the Podman docs recommend this) or with Homebrew:
```bash
brew install podman
```

* Create and start the Podman machine:
```bash
podman machine init
podman machine start
```

* Verify the version is 5.x and that containers run:
```bash
podman --version
podman run --rm quay.io/podman/hello
```

### Linux
Podman on Linux needs cgroups v2 and an active Podman user socket.

* Install Podman, e.g. `sudo apt install podman` or `sudo dnf install podman`
* Start the user socket, and enable it so it starts at login:
```bash
systemctl --user enable --now podman.socket
```

* Check that cgroups v2 is used (should print `v2`):
```bash
podman info --format '{{.Host.CgroupsVersion}}'
```

## Install OpenShell
* Run the installer. It installs the CLI, the policy prover and a local gateway. On macOS it uses Homebrew and runs the gateway as a Homebrew service at `https://localhost:17670`. On Linux it runs as a systemd user service.
```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
```

### Use Podman for the gateway
If you don't set a driver, the gateway auto-detects one. It tries Kubernetes first, then Podman, then Docker. To make sure it uses Podman, set the driver in `~/.config/openshell/gateway.toml`:
```toml
[openshell.gateway]
compute_driver = "podman"
```
The gateway finds the Podman socket by itself, including the `podman machine` socket on macOS.

* Validate the config, then restart the gateway:
```bash
openshell-gateway config preflight --path ~/.config/openshell/gateway.toml

# macOS
brew services restart openshell
# Linux
systemctl --user restart openshell-gateway
```

### Verify the installation
```bash
openshell status
```
* If something is wrong, check the gateway service: `brew services list` on macOS, or `journalctl --user -u openshell-gateway -f` on Linux
* Quick test with the default sandbox image (a minimal Ubuntu without an agent):
```bash
openshell sandbox create --name demo
```

## Credentials in .env
Keys and tokens go in `.env` in this folder. Start from the template; `.env` is ignored by git (see [.gitignore](../.gitignore)):
```bash
cp .env.example .env
```
Then fill in the values, e.g.:
```
OPENROUTER_API_KEY=sk-or-...
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```
`openshell provider create --from-existing` reads them from the environment, so they must be *exported*. A plain `source .env` doesn't export lines without `export`. Load the file in a subshell, only for the command that needs it:
```bash
(set -a; . ./.env; openshell provider create ...)
```
* `set -a` exports the variables, so `openshell` can read them.
* The parentheses run everything in a subshell. The secrets are gone when it ends, so they don't stay in your terminal's environment, where every program you start later would get them.
* `.env` should only be readable by you: `chmod 600 .env`
