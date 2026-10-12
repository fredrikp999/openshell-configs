#!/bin/sh
# Start an agent sandbox, either in the terminal or in VS Code.
#
#   bin/sandbox.sh <claude|opencode|agy> [name] [--vscode|--acp] [--browser|--hyperframes]
#                  [--forward PORT] [--workdir DIR] [-- agent args...]
#
#   bin/sandbox.sh claude                      # Claude in this terminal, sandbox claude-agent1
#   bin/sandbox.sh claude my-task --vscode     # open sandbox my-task in VS Code
#   bin/sandbox.sh opencode oc-task            # OpenCode in this terminal
#   bin/sandbox.sh agy ag-task                 # Antigravity CLI in this terminal
#   bin/sandbox.sh claude my-task -- -p 'reply with OK'   # pass args to the agent
#   bin/sandbox.sh opencode oc-task --acp      # ACP over stdio, for a UI/client
#   bin/sandbox.sh claude web-task --browser   # Claude with a headless browser
#   bin/sandbox.sh claude my-video --hyperframes --forward 3102   # HyperFrames
#
# --acp runs the agent's Agent Client Protocol server (JSON-RPC over stdin and
# stdout) instead of the terminal UI. A client spawns this script as its agent
# process; nothing is printed to stdout except the protocol. Messages go to
# stderr. OpenCode has `opencode acp` built in; for Claude the image has the
# ACP adapter claude-agent-acp, started by claude-acp-start.
#
# --browser (Claude only) creates the sandbox from the claude-browser image
# with policies/browser.yaml, which lists the sites the browser may open. It
# only matters when the sandbox is created.
#
# --hyperframes (Claude only) is the same with the claude-hyperframes image and
# policies/hyperframes.yaml: HyperFrames, FFmpeg and its skills on top of the
# browser.
#
# --forward PORT forwards 127.0.0.1:PORT on this machine to the same port in
# the sandbox (in the background, if not already forwarded), so you can open
# what the agent serves there, e.g. the HyperFrames preview.
#
# The sandbox is created on first use, and reused after that. It runs
# `sleep infinity` as its main process, so it keeps running when you quit the
# agent or close VS Code, and you can switch between both ways of working.
# Delete it with `openshell sandbox delete <name>`.
#
# Requires the provider and image from docs/agents.md (claude / claude-sandbox,
# claude-browser or claude-hyperframes, openrouter / opencode-sandbox). agy
# (agy-sandbox) has no provider: you log in inside the sandbox on first start,
# and policies/antigravity.yaml allows the Google hosts it needs. It has no ACP
# mode.
set -eu

usage() { sed -n "2,43p" "$0" | sed 's/^# \{0,1\}//'; exit 1; }

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
    model=${OPENCODE_MODEL:-openrouter/nvidia/nemotron-3.5-lightning:free}
    # The model goes into a command line and a JSON config, so only allow the
    # characters model ids use. Anything else (quotes, spaces) could add words
    # or config keys.
    case $model in
      ''|*[!A-Za-z0-9._:/@~+-]*)
        echo "OPENCODE_MODEL '$model' is not a valid model id." >&2; exit 1 ;;
    esac
    set_cmd() { cmd="opencode -m $model"; } ;;
  agy)
    image=agy-sandbox:latest
    provider=
    set_cmd() { cmd="agy"; } ;;
  *) usage ;;
esac
set_cmd

name=$agent-agent1
case ${1:-} in ''|-*) ;; *) name=$1; shift ;; esac

vscode=false
acp=false
browser=false
hyperframes=false
forward=
workdir=/sandbox
while [ $# -gt 0 ]; do
  case $1 in
    --vscode) vscode=true; shift ;;
    --acp) acp=true; shift ;;
    --browser) browser=true; shift ;;
    --hyperframes) hyperframes=true; shift ;;
    --forward) forward=$2; shift 2 ;;
    --workdir|-w) workdir=$2; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done

$vscode && $acp && { echo "Use either --vscode or --acp, not both." >&2; exit 1; }
if $acp; then
  case $agent in
    claude) cmd="claude-acp-start" ;;
    opencode) cmd="opencode acp" ;;
    agy) echo "agy has no ACP mode." >&2; exit 1 ;;
  esac
fi

policy=$(dirname "$0")/../policies/vscode-terminal.yaml
if [ "$agent" = agy ]; then
  policy=$(dirname "$0")/../policies/antigravity.yaml
fi
if $browser; then
  [ "$agent" = claude ] || { echo "--browser is only for claude." >&2; exit 1; }
  image=claude-browser:latest
  policy=$(dirname "$0")/../policies/browser.yaml
fi
if $hyperframes; then
  [ "$agent" = claude ] || { echo "--hyperframes is only for claude." >&2; exit 1; }
  $browser && { echo "Use either --browser or --hyperframes, not both." >&2; exit 1; }
  image=claude-hyperframes:latest
  policy=$(dirname "$0")/../policies/hyperframes.yaml
fi
case $forward in
  '') ;;
  *[!0-9]*) echo "--forward needs a port number." >&2; exit 1 ;;
esac

phase() { openshell sandbox list 2>/dev/null | awk -v n="$1" '$1==n {print $NF}'; }

p=$(phase "$name")
case $p in
  '')
    echo "Creating sandbox $name ($image, provider ${provider:-none})..." >&2
    openshell sandbox create \
      --name "$name" \
      --from "$image" \
      ${provider:+--provider "$provider"} \
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

if [ -n "$forward" ]; then
  if openshell forward list 2>/dev/null | awk -v n="$name" -v p="$forward" '$2==n && $4==p {f=1} END {exit !f}'; then
    echo "Port $forward is already forwarded to $name: http://127.0.0.1:$forward/" >&2
  # Its output is closed so the background forward doesn't hold this script's
  # stdout open (which matters for --acp, where stdout is the protocol).
  elif openshell forward start "$forward" "$name" -d </dev/null >/dev/null 2>&1; then
    echo "Forwarding http://127.0.0.1:$forward/ to port $forward in $name." >&2
  else
    echo "Could not forward port $forward; is it in use on this machine? (lsof -i :$forward)" >&2
    exit 1
  fi
fi

if $vscode; then
  exec openshell sandbox connect "$name" --editor vscode
elif $acp; then
  # No pty and no login shell, so nothing but JSON-RPC reaches stdout.
  # OpenCode's `acp` has no -m flag, so the model goes in through its config env
  # ($model was checked above, so it can't break out of the JSON string).
  # shellcheck disable=SC2086
  if [ "$agent" = opencode ]; then
    set -- --env "OPENCODE_CONFIG_CONTENT={\"model\":\"$model\"}" -- $cmd "$@"
  else
    set -- -- $cmd "$@"
  fi
  exec openshell sandbox exec "$name" --no-tty --no-login-shell --workdir "$workdir" "$@"
else
  # $cmd is split on purpose: it holds the agent command and its default args.
  # shellcheck disable=SC2086
  exec openshell sandbox exec "$name" --workdir "$workdir" -- $cmd "$@"
fi
