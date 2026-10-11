# Isolation on macOS
How well a sandbox is separated from your Mac when OpenShell runs on a Podman machine, what it's weak at, and how it compares to other ways of running containers.

**Short answer:** the VM is a strong boundary, but by default a Podman machine mounts the home folders read-write. A sandbox that escapes its container doesn't get into macOS, but it does get to read and change every file in your home folder.

## The layers
From the agent outwards, with Podman's defaults on macOS:

| Layer | What it gives you |
|---|---|
| OpenShell sandbox | Network denied by default and filtered by a proxy, credentials only as placeholders, syscall filter, filesystem rules from the [policy](customizing.md#sandbox-policies) |
| Container | Rootless Podman (`crun`): user namespaces, limited capabilities, seccomp, SELinux. A machine created with `--rootful` runs containers as root in the VM instead |
| Linux VM | Fedora CoreOS on Apple's hypervisor (the `applehv` or `libkrun` provider), with its own kernel |
| macOS | Only reachable through what the VM exposes: the shared folders and the Podman API |

Check a machine: `podman machine list` shows the VM type, `inspect` prints `false` for rootless, `info` shows rootless, seccomp and SELinux, `getenforce` should print `Enforcing`, and the last command lists the host folders shared with the VM:
```bash
podman machine list
podman machine inspect --format '{{.Rootful}}'
podman info --format '{{.Host.Security}}'
podman machine ssh getenforce
podman machine ssh 'mount | grep virtiofs'
```
(The commands in this doc have no comments on the same line: zsh, the default shell on macOS, doesn't treat `#` as a comment when you paste commands, unless you've run `setopt interactive_comments`.)

## Where it's weak
* **Your home folder is shared with the VM.** `podman machine init` mounts `/Users`, `/private` and `/var/folders` read-write by default. So the VM protects your macOS processes, the Keychain and the network, but not your files. Whoever becomes the VM's user (`core`) can read `~/.ssh`, `~/.config/openshell` and a `.env` if you have one, edit `~/.zshrc`, or plant code in any of your repos.
* **Root in the VM is one step away.** `core` has passwordless `sudo`. Escaping the container is the hard part; after that there's nothing left in the way.
* **All sandboxes share one kernel.** A kernel bug that lets an agent out of one sandbox gives it the VM, and every other sandbox in it. Escaping the hypervisor into macOS is much harder and very rare.

In practice the likelier risk is at the top layer: an agent sending data through hosts you allowed. That's what the network rules and credential placeholders are for. A container escape needs a kernel or runtime exploit, which is unlikely from a coding agent, but if it happens the shared home folder decides how bad it is.

## Compared to the alternatives
From weakest to strongest separation from your Mac:

| Option | Model | Your files if a sandbox escapes | Notes |
|---|---|---|---|
| Containers directly on a Linux host | No VM | The whole host, as far as the kernel lets it | The host kernel is the only boundary |
| OrbStack | One shared VM, deeply integrated | Most of the Mac's filesystem, by design | Fast and convenient, the weakest boundary on a Mac |
| Docker Desktop | One shared VM, `dockerd` runs as root in it | The shared folders, `/Users` by default (configurable) | Enhanced Container Isolation (Business plan) adds user namespaces |
| **Podman machine (default)** | One shared VM, rootless containers, SELinux | `/Users` read-write | Better defaults inside the VM than Docker, same problem with the shared folder |
| Colima, Lima, Rancher Desktop | One shared VM | Depends on the mount settings; check before relying on them | Similar to Podman |
| **Podman machine without host mounts** | As above | Nothing, or one folder you choose | Same speed, much smaller blast radius. See [below](#a-podman-machine-without-host-mounts) |
| One VM per sandbox (OpenShell's MicroVM driver, Apple's `container` on macOS 26) | A kernel per sandbox | Only what you mount | No shared kernel between sandboxes. Check that OpenShell supports it on your setup first |
| A separate full VM (UTM, Tart, Parallels) with OpenShell inside, no shared folders | A VM you manage | Nothing | Heavier, and you maintain the VM |
| A remote or cloud machine | A different computer | Nothing on your Mac | Strongest separation, costs money and adds latency |

## A Podman machine without host mounts
The biggest gain for the least effort. Sandboxes get files through `openshell sandbox upload` and [git bundles](working-in-sandboxes.md#getting-code-in-and-out), not bind mounts, and `podman build` sends the build context over the API, so nothing in this repo should need the host folders in the VM.

* Make sure there's enough free disk space first: `df -h /System/Volumes/Data`. Each machine has its own disk image with its own copy of every image, and building the images here takes several GB. If the Mac runs out of space, the VM's filesystem shuts down and the build fails with `server probably quit: unexpected EOF` (the VM's console log, `$TMPDIR/podman/openshell.log`, then shows `I/O error, dev vda`).
* Create a second machine. Passing `--volume` replaces the default mounts; this one shares only one empty folder for anything you deliberately want to hand over:
```bash
mkdir -p ~/openshell-share
podman machine init openshell \
  --volume "$HOME/openshell-share:$HOME/openshell-share"
```
* Stop the current machine (only one can run at a time), start the new one, and check that only `openshell-share` is mounted:
```bash
podman machine stop
podman machine start openshell
podman machine ssh openshell 'mount | grep virtiofs'
```
* **The share is writable from the VM, even with `:ro`.** With the `applehv` provider (tested with Podman 5.8), `:ro` on the volume is ignored. Keep the folder empty except for what you hand over, and treat anything in it as untrusted. Check it with `podman machine ssh openshell "touch $HOME/openshell-share/x && echo writable"`. The double quotes make your Mac's `$HOME` used, which is also the share's path in the VM. Then delete `~/openshell-share/x`.
* Make it the default and restart the gateway, so it uses the new machine:
```bash
podman system connection default openshell
brew services restart openshell
```
* The new machine has no images yet: `make images`, then check that everything works with `bin/sandbox.sh claude test -- -p 'reply with OK'` and `make test`.
* Set `--cpus`, `--memory` and `--disk-size` on `init` as for your current machine (`podman machine list` shows them).
* To go back: make the old machine's connection the default again (`podman system connection list`), stop `openshell`, start the old machine and restart the gateway.
* Once the new machine works, remove the old one to get its disk space back: `podman machine rm <old machine>`. The disk image of a machine grows but never shrinks on its own.

This setup hasn't been tested end to end with this repo yet. In particular, check which machine the gateway uses (`podman --connection openshell ps` should list the sandbox while it runs).
