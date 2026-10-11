#!/bin/sh
# Watch the denied connections of all sandboxes, as a live table.
#
#   bin/watch-denied.sh [--sandbox NAME] [--all] [--raw] [--since DUR]
#
#   bin/watch-denied.sh                        # all sandboxes
#   bin/watch-denied.sh --sandbox my-task      # only my-task (-s for short)
#   bin/watch-denied.sh --since 1h             # start with the last hour
#   bin/watch-denied.sh --all                  # don't hide the known harmless denials
#   bin/watch-denied.sh --raw                  # the DENIED log lines themselves
#
# All sandboxes means every sandbox in `openshell sandbox list`, whatever its
# phase. The list is checked every 10 seconds, so sandboxes created later are
# watched too.
#
# The table has one row per sandbox and host: which sandbox was denied, how
# often, when last, and which binaries tried (by name; --raw shows the full
# paths, which is what a profile's `binaries` list needs). It is redrawn on
# every new denial. When stdout isn't a terminal, it prints one line per new
# row instead.
#
# Known harmless denials are hidden unless --all is given: Chromium's start-up
# checks (www.google.com, update.googleapis.com), VS Code Server's CDN and
# telemetry, and the MCP prompts/list and resources/list calls Claude Code
# makes to every server. See docs/troubleshooting.md.
#
# To allow a host, review the proposals with
# `openshell rule get <name> --status pending` (docs/customizing.md#network-rules).
# Stop with Ctrl-C.
set -eu

NOISE='www\.google\.com|update\.googleapis\.com|vscode-cdn\.net|events\.data\.microsoft\.com|prompts/list|resources/list'

all=0
raw=0
since=1m
only=
while [ $# -gt 0 ]; do
  case "$1" in
    -s|--sandbox) only="${2:?--sandbox needs a sandbox name}"; shift 2 ;;
    --all) all=1; shift ;;
    --raw) raw=1; shift ;;
    --since) since="${2:?--since needs a duration, e.g. 5m}"; shift 2 ;;
    -h|--help) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) echo "unexpected argument: $1 (one sandbox only: --sandbox $1)" >&2; exit 2 ;;
  esac
done

# One sandbox's DENIED lines, as "name<TAB>line", flushed line by line.
follow() {
  openshell logs "$1" --tail --since "$since" \
    | awk -v name="$1" '/DENIED/ { print name "\t" $0; fflush() }'
}

# Turns "name<TAB>line" into the table (or raw lines). Log lines look like:
#   [1791703672.439] [sandbox] [OCSF ] [ocsf] NET:REFUSE [MED] DENIED github.com [reason:...]
#   [1791703672.552] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/lib/git-core/git-remote-http(0) -> github.com:443 [reason:...]
# REFUSE (DNS) and OPEN (connect) are the same attempt, so a row counts the
# larger of the two.
# shellcheck disable=SC2016
SUMMARY='
function trunc(s, n) { return length(s) > n ? substr(s, 1, n - 1) "~" : s }
function clock(t,  s) {
  s = ((int(t) + tzoff) % 86400 + 86400) % 86400
  return sprintf("%02d:%02d:%02d", int(s / 3600), int(s % 3600 / 60), s % 60)
}
function row(a, b, c, d, e) {
  printf "%-14s %-40s %5s  %-8s  %s\n", a, b, c, d, e
}
function draw(  i, k) {
  printf "\033[H\033[J"
  printf "Denied connections - %s - since %s - Ctrl-C to stop\n\n", title, since
  row("SANDBOX", "HOST", "COUNT", "LAST", "BINARIES")
  for (i = 1; i <= n; i++) {
    k = order[i]
    row(trunc(sb[k], 14), trunc(dest[k], 40), nopen[k] > nref[k] ? nopen[k] : nref[k],
        clock(last[k]), trunc(bins[k], 40))
  }
  if (n == 0) print "(none yet)"
  if (hidden) printf "\n%d known harmless denials hidden (--all shows them)\n", hidden
  fflush()
}
BEGIN {
  FS = "\t"
  # date +%z, e.g. +0200, as seconds
  tzoff = (substr(tz, 2, 2) * 3600 + substr(tz, 4, 2) * 60) * (substr(tz, 1, 1) == "-" ? -1 : 1)
  if (tty && !raw) draw()
}
{
  name = $1; line = $2
  if (!all && line ~ noise) { hidden++; if (tty && !raw) draw(); next }
  if (raw) { print "[" name "] " line; fflush(); next }

  ts = substr(line, 2, index(line, "]") - 2) + 0
  ev = ""
  if (match(line, / [A-Z0-9]+:[A-Z_]+ \[/)) ev = substr(line, RSTART + 1, RLENGTH - 3)
  rest = substr(line, index(line, "DENIED ") + 7)
  sub(/ \[reason:[^]]*\]$/, "", rest)

  bin = ""
  if (ev == "NET:OPEN" && (p = index(rest, " -> "))) {
    bin = substr(rest, 1, p - 1); sub(/\([0-9]+\)$/, "", bin); sub(/.*\//, "", bin)
    d = substr(rest, p + 4); host = d; sub(/:[0-9]+$/, "", host)
  } else if (ev == "NET:REFUSE") {
    d = rest; host = rest
  } else {
    d = ev " " rest; host = d
  }

  k = name SUBSEP host
  if (!(k in last)) {
    order[++n] = k; sb[k] = name; dest[k] = d; bins[k] = ""
    if (!tty) { printf "[%s] new denial: %s%s\n", name, d, (bin != "" ? " (" bin ")" : ""); fflush() }
  }
  if (d != host) dest[k] = d                  # prefer host:port once seen
  if (ev == "NET:REFUSE") nref[k]++; else nopen[k]++
  if (bin != "" && index("," bins[k] ",", "," bin ",") == 0)
    bins[k] = bins[k] == "" ? bin : bins[k] "," bin
  last[k] = ts
  if (tty) draw()
}'

title=${only:-all sandboxes}
if [ -t 1 ]; then tty=1; else tty=0; fi

# On Ctrl-C or kill, stop the log streams too. Only this script's own
# processes: `kill 0` would also hit a parent script in the same group.
# Parents go before their children, so no shell is left to report the
# children as "Terminated".
killtree() {
  set -- "$1" $(pgrep -P "$1")
  kill "$1" 2>/dev/null || true
  shift
  for child do killtree "$child"; done
}
stop() {
  trap - INT TERM
  for child in $(pgrep -P $$); do killtree "$child"; done
  exit 130
}
trap stop INT TERM

# Follow the one sandbox, or every sandbox in the list, starting a stream for
# each new name as it appears.
{
  if [ -n "$only" ]; then
    follow "$only" &
    wait
  else
    seen=" "
    while :; do
      for name in $(openshell sandbox list 2>/dev/null | awk 'NR > 1 { print $1 }'); do
        case "$seen" in
          *" $name "*) ;;
          *) seen="$seen$name "; follow "$name" & ;;
        esac
      done
      sleep 10
    done
  fi
} | awk -v noise="$NOISE" -v all="$all" -v raw="$raw" \
        -v tty="$tty" -v title="$title" -v since="$since" -v tz="$(date +%z)" \
        "$SUMMARY" &
wait
