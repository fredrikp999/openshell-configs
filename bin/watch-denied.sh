#!/bin/sh
# Stream the DENIED lines from one or more sandboxes' logs, live.
#
#   bin/watch-denied.sh [--all] [--since DUR] [name...]
#
#   bin/watch-denied.sh                        # last-used sandbox
#   bin/watch-denied.sh my-task                # one sandbox
#   bin/watch-denied.sh my-task web-task       # several, each line prefixed [name]
#   bin/watch-denied.sh --since 1h my-task     # start with the last hour
#   bin/watch-denied.sh --all my-task          # don't hide the known harmless denials
#
# Known harmless denials are hidden unless --all is given: Chromium's start-up
# checks (www.google.com, update.googleapis.com), VS Code Server's CDN and
# telemetry, and the MCP prompts/list and resources/list calls Claude Code
# makes to every server. See docs/troubleshooting.md.
#
# Each denied connection shows up as two lines: NET:REFUSE with the host, and
# NET:OPEN with the binary path that tried it. To allow a host, review the
# proposals with `openshell rule get <name> --status pending`
# (docs/customizing.md#network-rules). Stop with Ctrl-C.
set -eu

NOISE='www\.google\.com|update\.googleapis\.com|vscode-cdn\.net|events\.data\.microsoft\.com|prompts/list|resources/list'

all=0
since=1m
while [ $# -gt 0 ]; do
  case "$1" in
    --all) all=1; shift ;;
    --since) since="${2:?--since needs a duration, e.g. 5m}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done

# Filter and prefix in awk, flushing every line so nothing waits in a buffer.
watch() {
  # $1: sandbox name, empty for the last-used one; $2: line prefix
  openshell logs ${1:+"$1"} --tail --since "$since" \
    | awk -v prefix="$2" -v noise="$NOISE" -v all="$all" \
        '/DENIED/ && (all || $0 !~ noise) { print prefix $0; fflush() }'
}

# On Ctrl-C or kill, stop the log streams too. Only this script's own
# processes: `kill 0` would also hit a parent script in the same group.
killtree() {
  for child in $(pgrep -P "$1"); do
    killtree "$child"
    kill "$child" 2>/dev/null || true
  done
}
trap 'trap - INT TERM; killtree $$; exit 130' INT TERM
if [ $# -le 1 ]; then
  watch "${1:-}" "" &
else
  for name in "$@"; do
    watch "$name" "[$name] " &
  done
fi
wait
