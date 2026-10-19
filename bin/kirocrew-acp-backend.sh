#!/bin/sh
# ACP backend wrapper for an external Kiro Crew (https://kiro.dev) running on
# this same Mac: spawns Claude Code's ACP adapter inside an OpenShell sandbox,
# for Kiro Crew to drive as its agent.acp_backend. No Kiro Crew runs inside the
# sandbox; any ACP-capable sandbox profile works (claude, browser, hyperframes,
# graphics, ...). See docs/extras.md#claude-code-as-an-acp-backend-for-an-external-kiro-crew.
#
# One-time setup on this Mac, where Kiro Crew's gateway runs:
#   1. chmod +x already done; copy this script, or use it in place.
#   2. Point Kiro Crew's claude harness at it and pick the sandbox profile and
#      name (KIROCREW_ACP_PROFILE defaults to "kirocrew-backend", which creates
#      a plain claude-sandbox that auto-creates whatever cwd Kiro Crew asks for
#      -- see profiles/kirocrew-backend.env; KIROCREW_ACP_SANDBOX defaults to
#      "kirocrew-claude"), in the environment the gateway process runs under (a
#      shell profile, or a launchd/systemd env file):
#        export CLAUDE_AGENT_ACP_BIN=/path/to/openshell-configs/bin/kirocrew-acp-backend.sh
#        export KIROCREW_ACP_SANDBOX=my-backend     # optional, a name of your choosing
#        export KIROCREW_ACP_PROFILE=hyperframes    # optional, a different profile (loses the cwd auto-create)
#   3. kirocrew config set agent.acp_backend claude
#   4. kirocrew restart
#
# The sandbox is created on first use (bin/sandbox.sh's usual behavior) and
# reused after that; delete it with `openshell sandbox delete <name>`.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
name=${KIROCREW_ACP_SANDBOX:-kirocrew-claude}
profile=${KIROCREW_ACP_PROFILE:-kirocrew-backend}

exec "$here/sandbox.sh" "$profile" "$name" --acp
