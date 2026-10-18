#!/bin/sh
# Start an agent sandbox, either in the terminal or in VS Code.
#
#   bin/sandbox.sh <profile> [name] [--vscode|--acp] [--workdir DIR]
#                  [--policy NAME|FILE] [--forward PORT[,PORT...]] [-- agent args...]
#
# A profile (profiles/<profile>.env) is a ready-made setup: which agent, image,
# policy and ports to use. Run without arguments to list the profiles. To add a
# variant, copy a profile file and change it. The sandbox is named after the
# profile unless you give another name.
#
#   bin/sandbox.sh claude                      # Claude in this terminal, sandbox claude
#   bin/sandbox.sh claude my-task --vscode     # open sandbox my-task in VS Code
#   bin/sandbox.sh opencode oc-task            # OpenCode in this terminal
#   bin/sandbox.sh agy ag-task                 # Antigravity CLI in this terminal
#   bin/sandbox.sh claude my-task -- -p 'reply with OK'   # pass args to the agent
#   bin/sandbox.sh opencode oc-task --acp      # ACP over stdio, for a UI/client
#   bin/sandbox.sh browser                     # Claude with a headless browser
#   bin/sandbox.sh hyperframes                 # Claude with HyperFrames (preview on 3102)
#   bin/sandbox.sh graphics                    # Claude with VectorCraft and PhotoCraft
#   bin/sandbox.sh kirocrew                    # Claude with Kiro Crew (dashboard on 5476)
#   bin/sandbox.sh kirocrew-readonly           # the same with no network access
#
# --vscode opens the sandbox in VS Code instead of running the agent here.
#
# --acp runs the agent's Agent Client Protocol server (JSON-RPC over stdin and
# stdout) instead of the terminal UI. A client spawns this script as its agent
# process; nothing is printed to stdout except the protocol. Messages go to
# stderr. OpenCode has `opencode acp` built in; for Claude the image has the
# ACP adapter claude-agent-acp, started by claude-acp-start; for agy the image
# has the community adapter google-antigravity-acp, started by agy-acp-start.
#
# --policy NAME|FILE replaces the profile's policy, with a file path or NAME for
# policies/NAME.yaml. The image decides which tools exist; the policy decides
# what the sandbox may reach. It only matters when the sandbox is created; change
# a running one with `openshell policy set`.
#
# --forward PORT[,PORT...] replaces the profile's ports. Each is forwarded from
# 127.0.0.1 on this machine to the same port in the sandbox (in the background, if
# not already forwarded), so you can open what the agent serves there. Give a
# list separated by commas, or repeat the option. A port from the profile only
# warns if it is taken; one you ask for with --forward stops the script.
#
# The sandbox is created on first use, and reused after that. It runs
# `sleep infinity` as its main process, so it keeps running when you quit the
# agent or close VS Code, and you can switch between both ways of working.
# Delete it with `openshell sandbox delete <name>`.
#
# Requires the provider and image from docs/agents.md (claude / claude-sandbox,
# claude-browser or claude-hyperframes, openrouter / opencode-sandbox). agy
# (agy-sandbox) has no provider: you log in inside the sandbox on first start,
# and policies/antigravity.yaml allows the Google hosts it needs. Log in once
# (bin/sandbox.sh agy <name>) before using --acp.
set -eu

here=$(dirname "$0")

usage() {
  sed -n '2,/^set -eu/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
  echo
  list_profiles
  exit 1
}

list_profiles() {
  echo "Profiles:"
  for f in "$here"/../profiles/*.env; do
    [ -f "$f" ] || continue
    printf '  %-18s %s\n' "$(basename "$f" .env)" "$(sed -n '1s/^# *//p' "$f")"
  done
}

# NAME|FILE -> path of the policy file
resolve_policy() {
  if [ -f "$1" ]; then echo "$1"
  elif [ -f "$here/../policies/$1.yaml" ]; then echo "$here/../policies/$1.yaml"
  else echo "No policy file '$1' (or policies/$1.yaml)." >&2; exit 1; fi
}

[ $# -ge 1 ] || usage
profile=$1; shift
case $profile in
  ''|-*|*[!a-z0-9-]*) usage ;;
esac
profile_file=$here/../profiles/$profile.env
if [ ! -f "$profile_file" ]; then
  echo "No profile '$profile' (profiles/$profile.env)." >&2
  list_profiles >&2
  exit 1
fi

agent=; image=; policy=; cmd=; forward=; optional_provider=
# shellcheck disable=SC1090
. "$profile_file"
case $agent in
  claude|opencode|agy) ;;
  *) echo "profiles/$profile.env: agent must be claude, opencode or agy (got '$agent')." >&2; exit 1 ;;
esac
[ -n "$image" ] && [ -n "$policy" ] || { echo "profiles/$profile.env needs image and policy." >&2; exit 1; }

case $agent in
  claude)
    provider=claude
    term_cmd="claude-start"
    acp_cmd="claude-acp-start" ;;
  opencode)
    provider=openrouter
    model=${OPENCODE_MODEL:-openrouter/nvidia/nemotron-3.5-lightning:free}
    # The model goes into a command line and a JSON config, so only allow the
    # characters model ids use. Anything else (quotes, spaces) could add words
    # or config keys.
    case $model in
      ''|*[!A-Za-z0-9._:/@~+-]*)
        echo "OPENCODE_MODEL '$model' is not a valid model id." >&2; exit 1 ;;
    esac
    term_cmd="opencode -m $model"
    acp_cmd="opencode acp" ;;
  agy)
    provider=
    term_cmd="agy"
    acp_cmd="agy-acp-start" ;;
esac

name=$profile
case ${1:-} in ''|-*) ;; *) name=$1; shift ;; esac

vscode=false
acp=false
forward_given=
policy_override=
workdir=/sandbox
while [ $# -gt 0 ]; do
  case $1 in
    --vscode) vscode=true; shift ;;
    --acp) acp=true; shift ;;
    --policy) [ $# -ge 2 ] || usage; policy_override=$2; shift 2 ;;
    --forward) [ $# -ge 2 ] || usage; forward_given=${forward_given:+$forward_given,}$2; shift 2 ;;
    --workdir|-w) [ $# -ge 2 ] || usage; workdir=$2; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done

$vscode && $acp && { echo "Use either --vscode or --acp, not both." >&2; exit 1; }
if $acp; then
  cmd=$acp_cmd
else
  cmd=${cmd:-$term_cmd}
fi

policy=$(resolve_policy "${policy_override:-$policy}")

# Ports from the profile only warn when they can't be forwarded; ports you ask for stop the script.
forward_soft=true
if [ -n "$forward_given" ]; then
  forward=$forward_given
  forward_soft=false
fi
case $forward in
  '') ;;
  *[!0-9,]*|,*|*,|*,,*) echo "--forward needs port numbers, separated by commas." >&2; exit 1 ;;
esac

extra_provider=
if [ -n "$optional_provider" ]; then
  if openshell provider list 2>/dev/null | awk -v p="$optional_provider" '$1==p {f=1} END {exit !f}'; then
    extra_provider=$optional_provider
  else
    echo "No provider '$optional_provider': it is off. To turn it on: bin/provider.sh $optional_provider" >&2
  fi
fi

phase() { openshell sandbox list 2>/dev/null | awk -v n="$1" '$1==n {print $NF}'; }

p=$(phase "$name")
case $p in
  '')
    echo "Creating sandbox $name ($image, provider ${provider:-none}${extra_provider:+, $extra_provider})..." >&2
    openshell sandbox create \
      --name "$name" \
      --from "$image" \
      ${provider:+--provider "$provider"} \
      ${extra_provider:+--provider "$extra_provider"} \
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
  fwd_list=$(openshell forward list 2>/dev/null || true)
  for port in $(echo "$forward" | tr ',' ' '); do
    if echo "$fwd_list" | awk -v n="$name" -v p="$port" '$2==n && $4==p {f=1} END {exit !f}'; then
      echo "Port $port is already forwarded to $name: http://127.0.0.1:$port/" >&2
    # Its output is closed so the background forward doesn't hold this script's
    # stdout open (which matters for --acp, where stdout is the protocol).
    elif openshell forward start "$port" "$name" -d </dev/null >/dev/null 2>&1; then
      echo "Forwarding http://127.0.0.1:$port/ to port $port in $name." >&2
    else
      echo "Could not forward port $port; is it in use on this machine? (lsof -i :$port)" >&2
      $forward_soft || exit 1
    fi
  done
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
