#!/bin/sh
# Start an agent sandbox, either in the terminal or in VS Code.
#
#   ./sandbox.sh <claude|opencode> [name] [--vscode|--acp] [--workdir DIR] [-- agent args...]
#
#   ./sandbox.sh claude                      # Claude in this terminal, sandbox claude-agent1
#   ./sandbox.sh claude my-task --vscode     # open sandbox my-task in VS Code
#   ./sandbox.sh opencode oc-task            # OpenCode in this terminal
#   ./sandbox.sh claude my-task -- -p 'reply with OK'   # pass args to the agent
#   ./sandbox.sh opencode oc-task --acp      # ACP over stdio, for a UI/client
#
# --acp runs the agent's Agent Client Protocol server (JSON-RPC over stdin and
# stdout) instead of the terminal UI. A client spawns this script as its agent
# process; nothing is printed to stdout except the protocol. Messages go to
# stderr. OpenCode has `opencode acp` built in; Claude needs an ACP adapter
# (`claude-code-acp`) in the image.
#
# The sandbox is created on first use, and reused after that. It runs
# `sleep infinity` as its main process, so it keeps running when you quit the
# agent or close VS Code, and you can switch between both ways of working.
# Delete it with `openshell sandbox delete <name>`.
#
# Requires the provider and image from the README (claude / claude-sandbox,
# openrouter / opencode-sandbox).
set -eu

usage() { sed -n "2,22p" "$0" | sed 's/^# \{0,1\}//'; exit 1; }

[ $# -ge 1 ] || usage
agent=$1; shift
case $agent in
  claude)
    image=claude-sandbox:latest
    provider=claude
    set_cmd() { cmd="claude-start"; } ;;
  opencode)
    image=opencode-sandbox:latest
    provider=openrouter
    set_cmd() { cmd="opencode -m ${OPENCODE_MODEL:-openrouter/nvidia/nemotron-3.5-lightning:free}"; } ;;
  *) usage ;;
esac
set_cmd

name=$agent-agent1
case ${1:-} in ''|-*) ;; *) name=$1; shift ;; esac

vscode=false
acp=false
workdir=/sandbox
while [ $# -gt 0 ]; do
  case $1 in
    --vscode) vscode=true; shift ;;
    --acp) acp=true; shift ;;
    --workdir|-w) workdir=$2; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done

$vscode && $acp && { echo "Use either --vscode or --acp, not both." >&2; exit 1; }
if $acp; then
  case $agent in
    claude) cmd="claude-code-acp" ;;
    opencode) cmd="opencode acp" ;;
  esac
fi

policy=$(dirname "$0")/policies/vscode-terminal.yaml

phase() { openshell sandbox list 2>/dev/null | awk -v n="$1" '$1==n {print $NF}'; }

p=$(phase "$name")
case $p in
  '')
    echo "Creating sandbox $name ($image, provider $provider)..." >&2
    openshell sandbox create \
      --name "$name" \
      --from "$image" \
      --provider "$provider" \
      --policy "$policy" \
      --detach \
      -- sleep infinity >/dev/null
    i=0
    until [ "$(phase "$name")" = Ready ]; do
      i=$((i + 1))
      if [ $i -gt 60 ]; then
        echo "Sandbox $name is not Ready after 3 minutes (phase: $(phase "$name"))." >&2
        exit 1
      fi
      sleep 3
    done ;;
  Ready) ;;
  *)
    echo "Sandbox $name exists but is $p." >&2
    echo "Delete it with 'openshell sandbox delete $name' and run this again." >&2
    exit 1 ;;
esac

if $vscode; then
  exec openshell sandbox connect "$name" --editor vscode
elif $acp; then
  # No pty and no login shell, so nothing but JSON-RPC reaches stdout.
  # shellcheck disable=SC2086
  # OpenCode's `acp` has no -m flag, so the model goes in through its config env.
  exec openshell sandbox exec "$name" --no-tty --no-login-shell --workdir "$workdir" \
    --env "OPENCODE_CONFIG_CONTENT={\"model\":\"${OPENCODE_MODEL:-openrouter/nvidia/nemotron-3.5-lightning:free}\"}" -- $cmd "$@"
else
  # $cmd is split on purpose: it holds the agent command and its default args.
  # shellcheck disable=SC2086
  exec openshell sandbox exec "$name" --workdir "$workdir" -- $cmd "$@"
fi
