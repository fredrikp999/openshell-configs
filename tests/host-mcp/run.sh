#!/bin/sh
# Test: a stdio MCP server in a container on the host, used from a sandbox
# over HTTP, with a protocol: mcp rule that allows one tool.
#
#   tests/host-mcp/run.sh [--claude] [--keep]
#
# 1. Starts @modelcontextprotocol/server-everything behind supergateway
#    (stdio -> Streamable HTTP) in a Podman container, port bound to
#    127.0.0.1 only.
# 2. Creates sandbox host-mcp-test (claude-sandbox image, claude provider),
#    looks up host.containers.internal in it, and sets the rule from
#    rule.yaml with that IP.
# 3. Checks from the sandbox: `echo` is allowed, `get-sum` is denied.
# --claude: also lets Claude Code call both tools (uses your subscription).
# --keep:   leave the sandbox and the container running afterwards.
#
# Requires the claude-sandbox image and the claude provider (see docs/agents.md).
set -eu

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

dir=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$dir/../.." && pwd)
sandbox=host-mcp-test
server=host-mcp-test-server
port=${PORT:-8000}
claude=false
keep=false
for a in "$@"; do
  case $a in
    --claude) claude=true ;;
    --keep) keep=true ;;
    *) usage ;;
  esac
done

tmp=$(mktemp -d)
cleanup() {
  rm -rf "$tmp"
  $keep && return
  openshell sandbox delete "$sandbox" >/dev/null 2>&1 || true
  podman rm -f "$server" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting MCP server container $server on 127.0.0.1:$port..."
podman rm -f "$server" >/dev/null 2>&1 || true
podman run -d --name "$server" -p "127.0.0.1:$port:8000" node:22-slim \
  npx -y supergateway --stdio "npx -y @modelcontextprotocol/server-everything" \
  --outputTransport streamableHttp --port 8000 >/dev/null
i=0
until curl -sf -o /dev/null -X POST "http://127.0.0.1:$port/mcp" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"run.sh","version":"1"}}}'; do
  i=$((i + 1))
  [ $i -le 60 ] || { echo "MCP server did not start; see 'podman logs $server'." >&2; exit 1; }
  sleep 3
done

echo "Creating sandbox $sandbox..."
openshell sandbox delete "$sandbox" >/dev/null 2>&1 || true
openshell sandbox create --name "$sandbox" --from claude-sandbox:latest --provider claude \
  --policy "$root/policies/vscode-terminal.yaml" --detach -- sleep infinity >/dev/null
i=0
until [ "$(openshell sandbox list | awk -v n="$sandbox" '$1==n {print $NF}')" = Ready ]; do
  i=$((i + 1))
  [ $i -le 60 ] || { echo "Sandbox $sandbox is not Ready after 3 minutes." >&2; exit 1; }
  sleep 3
done

ip=$(openshell sandbox exec "$sandbox" --no-tty -- getent hosts host.containers.internal | awk '{print $1; exit}')
[ -n "$ip" ] || { echo "host.containers.internal does not resolve in the sandbox." >&2; exit 1; }
echo "Host is $ip in the sandbox. Setting the policy..."
{ cat "$root/policies/vscode-terminal.yaml"; echo "network_policies:"
  sed -e "s/HOST_IP/$ip/" -e "s/PORT/$port/" "$dir/rule.yaml"; } > "$tmp/policy.yaml"
openshell policy set "$sandbox" --policy "$tmp/policy.yaml" --wait >/dev/null

openshell sandbox upload "$sandbox" "$dir/mcp_probe.js" /tmp >/dev/null
url=http://$ip:$port/mcp
fail=0
openshell sandbox exec "$sandbox" --no-tty -- node /tmp/mcp_probe.js "$url" echo allow || fail=1
openshell sandbox exec "$sandbox" --no-tty -- node /tmp/mcp_probe.js "$url" get-sum deny || fail=1

if $claude; then
  out=$(openshell sandbox exec "$sandbox" --no-tty -- sh -c "
    claude-start mcp add --transport http host-mcp $url >/dev/null &&
    claude -p 'Call the echo tool of the host-mcp MCP server with message hello-sandbox, then its get-sum tool with a=1 and b=2. Reply with the raw result or error of each call, one line each.' \
      --allowedTools mcp__host-mcp__echo,mcp__host-mcp__get-sum" 2>&1) || true
  echo "$out" | sed 's/^/  claude: /'
  if echo "$out" | grep -q 'hello-sandbox' && echo "$out" | grep -q 'policy_denied'; then
    echo "PASS claude: echo worked, get-sum was denied"
  else
    echo "FAIL claude: expected the echo result and a policy_denied error"; fail=1
  fi
fi

[ $fail -eq 0 ] && echo "All tests passed." || echo "Some tests failed; see 'openshell logs $sandbox' (use --keep)."
exit $fail
