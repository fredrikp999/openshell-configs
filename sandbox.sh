#!/bin/sh
# Start an agent sandbox, either in the terminal or in VS Code.
#
#   ./sandbox.sh <claude|opencode> [name] [--vscode] [--workdir DIR] [-- agent args...]
#
#   ./sandbox.sh claude                      # Claude in this terminal, sandbox claude-agent1
#   ./sandbox.sh claude my-task --vscode     # open sandbox my-task in VS Code
#   ./sandbox.sh opencode oc-task            # OpenCode in this terminal
#   ./sandbox.sh claude my-task -- -p 'reply with OK'   # pass args to the agent
#
# The sandbox is created on first use, and reused after that. It runs
# `sleep infinity` as its main process, so it keeps running when you quit the
# agent or close VS Code, and you can switch between both ways of working.
# Delete it with `openshell sandbox delete <name>`.
#
# Requires the provider and image from the README (claude / claude-sandbox,
# openrouter / opencode-sandbox).
set -eu

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

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
workdir=/sandbox
while [ $# -gt 0 ]; do
  case $1 in
    --vscode) vscode=true; shift ;;
    --workdir|-w) workdir=$2; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done

policy=$(dirname "$0")/policies/vscode-terminal.yaml

phase() { openshell sandbox list 2>/dev/null | awk -v n="$1" '$1==n {print $NF}'; }

p=$(phase "$name")
case $p in
  '')
    echo "Creating sandbox $name ($image, provider $provider)..."
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
else
  # $cmd is split on purpose: it holds the agent command and its default args.
  # shellcheck disable=SC2086
  exec openshell sandbox exec "$name" --workdir "$workdir" -- $cmd "$@"
fi
