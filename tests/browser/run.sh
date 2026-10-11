#!/bin/sh
# Test: the headless browser in the claude-browser image, with the network
# rules from policies/browser.yaml.
#
#   tests/browser/run.sh [--claude] [--keep]
#
# 1. Creates sandbox browser-test (claude-browser image, claude provider,
#    policies/browser.yaml) and starts a web server on 127.0.0.1:8080 in it.
# 2. Checks from the sandbox, through Playwright MCP: example.com (listed in
#    the policy) loads, www.wikipedia.org (not listed) is denied, and the
#    local server loads on 127.0.0.1 and localhost.
# --claude: also lets Claude Code open both sites (uses your subscription).
# --keep:   leave the sandbox running afterwards.
#
# Requires the claude-browser image and the claude provider (see docs/extras.md).
set -eu

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

dir=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$dir/../.." && pwd)
sandbox=browser-test
claude=false
keep=false
for a in "$@"; do
  case $a in
    --claude) claude=true ;;
    --keep) keep=true ;;
    *) usage ;;
  esac
done

cleanup() {
  $keep && return
  openshell sandbox delete "$sandbox" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Creating sandbox $sandbox..."
openshell sandbox delete "$sandbox" >/dev/null 2>&1 || true
openshell sandbox create --name "$sandbox" --from claude-browser:latest --provider claude \
  --policy "$root/policies/browser.yaml" --detach -- sleep infinity >/dev/null
i=0
until [ "$(openshell sandbox list | awk -v n="$sandbox" '$1==n {print $NF}')" = Ready ]; do
  i=$((i + 1))
  [ $i -le 60 ] || { echo "Sandbox $sandbox is not Ready after 3 minutes." >&2; exit 1; }
  sleep 3
done

openshell sandbox upload "$sandbox" "$dir/browser_probe.js" /tmp >/dev/null
echo "Starting a web server on 127.0.0.1:8080 in the sandbox..."
openshell sandbox exec "$sandbox" --no-tty -- sh -c '
  printf "<title>local-ok</title><p>hello</p>" > /tmp/index.html
  nohup node -e "require(\"http\").createServer((q, r) => r.end(require(\"fs\").readFileSync(\"/tmp/index.html\"))).listen(8080, \"127.0.0.1\")" >/dev/null 2>&1 &'

fail=0
probe() {
  openshell sandbox exec "$sandbox" --no-tty --workdir /sandbox -- node /tmp/browser_probe.js "$1" "$2" 2>/dev/null || fail=1
}
probe https://example.com/ allow
probe https://www.wikipedia.org/ deny
probe http://127.0.0.1:8080/ allow
probe http://localhost:8080/ allow

if $claude; then
  out=$(openshell sandbox exec "$sandbox" --no-tty --workdir /sandbox -- claude-start -p \
    'Use the playwright browser_navigate tool to open https://example.com/ and then https://www.wikipedia.org/. Reply with the page title or the raw error of each, one line each.' \
    --allowedTools mcp__playwright__browser_navigate 2>&1) || true
  echo "$out" | sed 's/^/  claude: /'
  if echo "$out" | grep -q 'Example Domain' && echo "$out" | grep -q 'ERR_NETWORK_ACCESS_DENIED'; then
    echo "PASS claude: example.com loaded, wikipedia.org was denied"
  else
    echo "FAIL claude: expected the example.com title and ERR_NETWORK_ACCESS_DENIED"; fail=1
  fi
fi

[ $fail -eq 0 ] && echo "All tests passed." || echo "Some tests failed; see 'openshell logs $sandbox' (use --keep)."
exit $fail
