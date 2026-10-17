#!/bin/sh
# Check that this machine is ready to run sandboxes, and say what's wrong.
#
#   bin/doctor.sh      (or: make doctor)
#
# Checks, in order: free disk space, Podman and its machine (macOS), the
# default Podman connection, the VM's clock against the Mac's, the clock job
# (bin/vm-clock.sh), the OpenShell gateway, the providers and the images.
# Each line starts with ok, warn or FAIL; a FAIL makes the exit status 1.
# Only reads; it changes nothing. See docs/troubleshooting.md for the fixes.
set -u

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[ $# -eq 0 ] || usage

failed=0
ok() { echo "ok    $*"; }
warn() { echo "warn  $*"; }
fail() { echo "FAIL  $*"; failed=1; }
mac=false
[ "$(uname)" = Darwin ] && mac=true

# Disk space: a full disk shuts down the VM's filesystem (docs/isolation.md).
if $mac; then vol=/System/Volumes/Data; else vol=$HOME; fi
free_gb=$(df -k "$vol" | awk 'NR==2 {print int($4 / 1048576)}')
if [ "$free_gb" -lt 5 ]; then
  fail "disk: only ${free_gb} GB free on $vol; builds and the VM need room (troubleshooting: unexpected EOF)"
elif [ "$free_gb" -lt 20 ]; then
  warn "disk: ${free_gb} GB free on $vol; building the images takes about 8 GB"
else
  ok "disk: ${free_gb} GB free"
fi

# Podman, and on macOS the machine and the default connection.
if ! command -v podman >/dev/null 2>&1; then
  fail "podman: not installed (docs/setup.md)"
else
  ok "podman: $(podman --version | awk '{print $NF}')"
  machine=
  if $mac; then
    machine=$(podman machine list --format '{{.Name}} {{.Running}}' | awk '$2=="true" {sub(/\*$/, "", $1); print $1; exit}')
    default=$(podman system connection list --format '{{.Name}} {{.Default}}' | awk '$2=="true" {print $1; exit}')
    if [ -z "$machine" ]; then
      fail "podman machine: none running (podman machine start)"
    else
      ok "podman machine: $machine is running"
      if [ "$default" = "$machine" ]; then
        ok "podman connection: the default is $default"
      else
        fail "podman connection: the default is ${default:-none}, not $machine (podman system connection default $machine, then restart the gateway)"
      fi
    fi
  fi
  if ! podman info >/dev/null 2>&1; then
    fail "podman: can't reach the Podman service (podman info)"
  fi
fi

# The VM's clock: a VM behind the Mac makes new sandboxes fail.
if $mac && [ -n "${machine:-}" ]; then
  now() { perl -MTime::HiRes=time -e 'printf "%.3f\n", time'; }
  before=$(now)
  vm=$(podman machine ssh "$machine" 'date -u +%s.%N' 2>/dev/null)
  after=$(now)
  if [ -z "$vm" ]; then
    fail "clock: can't read the VM's clock (podman machine ssh $machine)"
  else
    offset=$(echo "$vm $before $after" | awk '{printf "%.2f", $1 - ($2 + $3) / 2}')
    if echo "$offset" | awk '{exit !($1 > 1 || $1 < -1)}'; then
      fail "clock: the VM is ${offset}s off the Mac; new sandboxes fail until it's fixed (bin/vm-clock.sh)"
    else
      ok "clock: the VM is ${offset}s off the Mac"
    fi
  fi
  if launchctl print "gui/$(id -u)/com.github.openshell-configs.vm-clock" >/dev/null 2>&1; then
    ok "clock job: installed"
  else
    warn "clock job: not installed; the VM's clock falls behind when the Mac sleeps (bin/vm-clock.sh --install)"
  fi
fi

# The gateway, the providers and the images.
if ! command -v openshell >/dev/null 2>&1; then
  fail "openshell: not installed (docs/setup.md)"
elif ! openshell status 2>/dev/null | grep -q 'Status: Connected'; then
  fail "gateway: not connected (openshell status; brew services restart openshell)"
else
  ok "gateway: connected"
  providers=$(openshell provider list 2>/dev/null | awk 'NR>1 {print $1}' | tr '\n' ' ')
  for p in claude openrouter; do
    case " $providers" in
      *" $p "*) ok "provider: $p" ;;
      *) warn "provider: $p missing (bin/provider.sh $( [ $p = openrouter ] && echo opencode || echo $p ))" ;;
    esac
  done
fi
if command -v podman >/dev/null 2>&1; then
  for i in claude-sandbox claude-browser claude-hyperframes claude-graphics opencode-sandbox agy-sandbox agy-hyperframes agy-node agy-python; do
    if podman image exists "$i:latest" 2>/dev/null; then ok "image: $i"; else warn "image: $i missing (make $i)"; fi
  done
fi

exit $failed
