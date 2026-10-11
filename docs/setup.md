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
```
On macOS:
```bash
brew services restart openshell
```
On Linux:
```bash
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

## Credentials
A provider's key or token is only needed on the host once: when you create the provider (and again when you rotate the token). After that it's stored in the gateway, and the sandbox only ever sees a placeholder. So the question is where the key lives on your machine until you create the provider, and in between rotations.

[bin/provider.sh](../bin/provider.sh) looks for the credential in this order, and uses the first one it finds:
1. **The environment**, e.g. set by another secrets manager for that one command (see [Other secrets managers](#other-secrets-managers))
2. **The macOS Keychain** (recommended)
3. **`.env`** in this folder (fallback)

It tells you which one it used, never prints the value, and passes it to `openshell` in the environment of a subshell, never on a command line (where `ps` would show it).

| Agent | Variable | Where to get it |
|---|---|---|
| Claude Code | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` on the host, see [Create an OAuth token](agents.md#create-an-oauth-token-on-the-host) |
| OpenCode | `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |

### In the Keychain (recommended)
Store the key as a generic password with service `openshell` and the variable name as account. `-w` without a value makes `security` prompt for it, so it doesn't end up in your shell history, and `-U` replaces an existing one:
```bash
security add-generic-password -U -s openshell -a CLAUDE_CODE_OAUTH_TOKEN -w
security add-generic-password -U -s openshell -a OPENROUTER_API_KEY -w
```
Then create the provider with `bin/provider.sh claude` (or `opencode`), and after a new token with `bin/provider.sh --update claude`.

* Check that it's there, without showing it: `security find-generic-password -s openshell -a CLAUDE_CODE_OAUTH_TOKEN >/dev/null && echo found`
* Remove it: `security delete-generic-password -s openshell -a CLAUDE_CODE_OAUTH_TOKEN`
* Items created with `security` can be read back by `security` without a prompt, as long as your login keychain is unlocked. To be asked every time, open the item in Keychain Access and remove `security` from *Access Control*.

### In .env (fallback)
If you're not on macOS, or prefer a file, put the keys in `.env` in this folder. Start from the template; `.env` is ignored by git (see [.gitignore](../.gitignore)):
```bash
cp .env.example .env
chmod 600 .env
```
Then fill in the values, e.g. `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...`. `bin/provider.sh` refuses a `.env` that others can read or write, and reads only the one line it needs instead of running the file as shell code.

Why `.env` isn't preferred:
* **It's a plaintext copy that outlives its use.** The gateway already holds the key after `provider create`, but `.env` keeps another copy in your project folder for as long as the token is valid (a year for `claude setup-token`).
* **Anything running as you can read it.** `chmod 600` only keeps out other users. Your editor and its extensions, an agent running on the host, build tools, `npm install` scripts and malware all run as you. The Keychain encrypts the key and only hands it out while you're logged in, and can be set to ask first.
* **It spreads.** Backups (Time Machine, cloud sync of the folder), `zip` or `rsync` of the project, and copies like `.env.bak` or `.env.old` all carry the key in plaintext. `.gitignore` only protects against `git add`, and one mistake there (a renamed file, `git add -f`, a different repo's `.gitignore`) publishes the key.
* **It's easy to show by accident.** `cat`, a screen share, or an AI assistant asked to "look at the config" reads it just like any other file.
* **Loading it is error-prone.** A plain `source .env` doesn't export the variables, and `set -a; . ./.env` in your main shell leaves the keys in its environment, where every program you start later gets them. Sourcing also runs the file as shell code.

If you do use `.env`, delete it once the provider is created, or keep the key in a password manager and only paste it in when you need it.

### Other secrets managers
Any secrets manager works, because the environment comes first: let the manager set the variable for just the one command, and `bin/provider.sh` uses it. For example:
* **1Password CLI.** `.env.tpl` holds references, not secrets, e.g. `CLAUDE_CODE_OAUTH_TOKEN=op://Private/Claude setup-token/credential`:
```bash
op run --env-file=.env.tpl -- bin/provider.sh claude
```
* **Bitwarden Secrets Manager:**
```bash
bws run -- bin/provider.sh claude
```
* **Linux Secret Service** (GNOME Keyring, KWallet), **pass**, or anything else that prints the secret:
```bash
CLAUDE_CODE_OAUTH_TOKEN="$(secret-tool lookup service openshell account CLAUDE_CODE_OAUTH_TOKEN)" bin/provider.sh claude
CLAUDE_CODE_OAUTH_TOKEN="$(pass show openshell/claude)" bin/provider.sh claude
```
`VAR=value command` sets the variable only for that command, so it doesn't stay in your shell. The same works with team vaults such as HashiCorp Vault (`vault kv get -field=...`), AWS Secrets Manager or Azure Key Vault, which also give you access logs and central rotation.

### Token expiry
`claude setup-token` tokens are valid for a year. To have OpenShell track that, set the expiry on the provider, e.g. a year from the day you created the token:
```bash
openshell provider update claude --credential-expires-at oauth_token=2027-10-11T00:00:00Z
```
To rotate: create a new token, store it (`security add-generic-password -U ...` replaces the old one), and run `bin/provider.sh --update claude`. Running sandboxes pick up the new credential for new processes.
