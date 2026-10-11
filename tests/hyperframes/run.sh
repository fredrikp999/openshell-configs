#!/bin/sh
# Test: HyperFrames in the claude-hyperframes image, with policies/hyperframes.yaml.
#
#   tests/hyperframes/run.sh [--claude] [--keep] [--port PORT]
#
# 1. Creates sandbox hyperframes-test (claude-hyperframes image, claude
#    provider, policies/hyperframes.yaml) and a project with `hyperframes init`.
# 2. Checks that `hyperframes check` has no runtime errors (GSAP loads from
#    the CDN through the OpenShell proxy) and that a render gives an MP4.
# 3. Starts the preview on PORT (default 3102) in the sandbox, forwards the
#    port, and checks that HyperFrames Studio answers on this machine.
# --claude: also has Claude Code make and render a short video (uses your
#           subscription).
# --keep:   leave the sandbox and the forward running afterwards.
#
# Requires the claude-hyperframes image and the claude provider (see docs/extras.md).
set -eu

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

root=$(cd "$(dirname "$0")/../.." && pwd)
sandbox=hyperframes-test
claude=false
keep=false
port=3102
while [ $# -gt 0 ]; do
  case $1 in
    --claude) claude=true; shift ;;
    --keep) keep=true; shift ;;
    --port) port=$2; shift 2 ;;
    *) usage ;;
  esac
done

cleanup() {
  $keep && return
  openshell forward stop "$port" "$sandbox" >/dev/null 2>&1 || true
  openshell sandbox delete "$sandbox" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if lsof -nP -i ":$port" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $port is in use on this machine; pick another with --port." >&2
  exit 1
fi

echo "Creating sandbox $sandbox..."
openshell sandbox delete "$sandbox" >/dev/null 2>&1 || true
openshell sandbox create --name "$sandbox" --from claude-hyperframes:latest --provider claude \
  --policy "$root/policies/hyperframes.yaml" --detach -- sleep infinity >/dev/null
i=0
until [ "$(openshell sandbox list | awk -v n="$sandbox" '$1==n {print $NF}')" = Ready ]; do
  i=$((i + 1))
  [ $i -le 60 ] || { echo "Sandbox $sandbox is not Ready after 3 minutes." >&2; exit 1; }
  sleep 3
done

run() { openshell sandbox exec "$sandbox" --no-tty --workdir /sandbox -- sh -c "$1" 2>&1; }
fail=0
pass() { echo "PASS $1"; }
nope() { echo "FAIL $1"; fail=1; }

echo "Creating and rendering a project..."
run 'hyperframes-init && hyperframes init demo --non-interactive' >/dev/null
out=$(run 'cd demo && hyperframes check </dev/null') || true
if echo "$out" | grep -A1 '^Runtime' | grep -q '0 errors'; then
  pass "check: no runtime errors (GSAP loaded through the proxy)"
else
  nope "check: runtime errors"; echo "$out" | sed -n '/^Runtime/,/^Layout/p' | sed 's/^/  /'
fi
out=$(run 'cd demo && hyperframes render --quality draft -o out.mp4 </dev/null && wc -c < out.mp4') || true
size=$(echo "$out" | tail -n1)
case $size in
  ''|*[!0-9]*) nope "render: no MP4"; echo "$out" | tail -5 | sed 's/^/  /' ;;
  *) [ "$size" -gt 1000 ] && pass "render: out.mp4, $size bytes" || nope "render: out.mp4 is only $size bytes" ;;
esac

echo "Starting the preview on port $port and forwarding it..."
run "cd demo && hyperframes preview --background --no-open --port $port </dev/null" >/dev/null
openshell forward start "$port" "$sandbox" -d </dev/null >/dev/null 2>&1
i=0
until curl -s -m 5 -o /dev/null "http://127.0.0.1:$port/"; do
  i=$((i + 1)); [ $i -le 10 ] || break; sleep 2
done
if curl -s -m 10 "http://127.0.0.1:$port/" | grep -q '<title>HyperFrames Studio'; then
  pass "preview: HyperFrames Studio at http://127.0.0.1:$port/"
else
  nope "preview: no HyperFrames Studio at http://127.0.0.1:$port/"
fi

if $claude; then
  out=$(openshell sandbox exec "$sandbox" --no-tty --workdir /sandbox -- claude-start -p \
    'Use the hyperframes skills. Create a 3-second HyperFrames project in /sandbox/hello (start with `npx hyperframes init hello --non-interactive`) where the title "Hello" fades in with GSAP. Run `npx hyperframes check` in it and fix any errors, then render a draft with `npx hyperframes render --quality draft -o hello.mp4`. Reply with only the size of hello.mp4 in bytes.' \
    --allowedTools Skill Read Write Edit Glob Grep 'Bash(npx hyperframes:*)' 'Bash(cd /sandbox/hello && npx hyperframes:*)' 'Bash(ls:*)' 'Bash(wc:*)' 2>&1) || true
  echo "$out" | tail -3 | sed 's/^/  claude: /'
  if run 'test -s /sandbox/hello/hello.mp4' >/dev/null; then
    pass "claude: made and rendered /sandbox/hello/hello.mp4"
  else
    nope "claude: no /sandbox/hello/hello.mp4"
  fi
fi

[ $fail -eq 0 ] && echo "All tests passed." || echo "Some tests failed; see 'openshell logs $sandbox' (use --keep)."
exit $fail
