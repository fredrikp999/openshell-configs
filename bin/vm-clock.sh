#!/bin/sh
# Keep the running Podman machine's clock in step with the Mac's.
#
#   bin/vm-clock.sh               check once, and set the VM's clock if it's off
#   bin/vm-clock.sh --install     run the check every 30 s in the background (launchd)
#   bin/vm-clock.sh --uninstall   stop and remove the background job
#
# The VM's clock stands still while the Mac sleeps, and chrony in the VM can
# take a long time to catch up. Until then, new sandboxes fail with
# ContainerExited, because the supervisor rejects the gateway's token as
# "issued in the future" (the gateway runs on the Mac and uses the Mac's
# clock). See "A Podman machine with minimal host mounts" in docs/isolation.md.
#
# The check sets the VM's clock from the Mac's when they differ by more than
# a second, and does nothing when no machine is running. The background job
# logs its corrections to ~/Library/Logs/openshell-vm-clock.log.
set -eu

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

label=com.github.openshell-configs.vm-clock
plist="$HOME/Library/LaunchAgents/$label.plist"
log="$HOME/Library/Logs/openshell-vm-clock.log"

# The Mac's time in seconds, with milliseconds.
now() { perl -MTime::HiRes=time -e 'printf "%.3f\n", time'; }

check() {
  machine=$(podman machine list --format '{{.Name}} {{.Running}}' | awk '$2=="true" {sub(/\*$/, "", $1); print $1; exit}')
  [ -n "$machine" ] || return 0
  before=$(now)
  vm=$(podman machine ssh "$machine" 'date -u +%s.%N')
  after=$(now)
  # Compare with the middle of the round trip; correct when more than 1 s off.
  offset=$(echo "$vm $before $after" | awk '{printf "%.2f", $1 - ($2 + $3) / 2}')
  if echo "$offset" | awk '{exit !($1 > 1 || $1 < -1)}'; then
    # Add the round trip, so the VM ends up a little ahead rather than
    # behind: a VM that's behind can still reject a token issued just now.
    podman machine ssh "$machine" "sudo date -u -s @$(echo "$(now) $before $after" | awk '{printf "%.3f", $1 + $3 - $2}') >/dev/null"
    echo "$(date '+%Y-%m-%d %H:%M:%S') $machine was ${offset}s off, set from the Mac's clock"
  fi
}

install() {
  script=$(cd "$(dirname "$0")" && pwd)/vm-clock.sh
  mkdir -p "$(dirname "$plist")" "$(dirname "$log")"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$script</string></array>
  <key>StartInterval</key><integer>30</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$(dirname "$(command -v podman)"):/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "Installed $label: checks every 30 s, log in $log"
  echo "It runs $script, so keep the repo where it is (or run --install again after moving it)."
}

uninstall() {
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$plist"
  echo "Removed $label."
}

case ${1:-} in
  "") check ;;
  --install) install ;;
  --uninstall) uninstall ;;
  *) usage ;;
esac
