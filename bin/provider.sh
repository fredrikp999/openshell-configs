#!/bin/sh
# Import a provider profile and create the provider, with the credential from
# the macOS Keychain (or, as a fallback, from .env).
#
#   bin/provider.sh [--update] <claude|opencode|replicate>
#
#   bin/provider.sh claude            # profile claude-code-oauth, provider claude
#   bin/provider.sh opencode          # profile openrouter, provider openrouter
#   bin/provider.sh replicate         # profile replicate, provider replicate (--graphics)
#   bin/provider.sh --update claude   # put a new token in an existing provider
#
# The credential is taken from the first of these that has it:
#   1. the environment, e.g. from another secrets manager:
#        op run --env-file=.env.tpl -- bin/provider.sh claude
#   2. the macOS Keychain, service "openshell", account = the variable name:
#        security add-generic-password -U -s openshell -a CLAUDE_CODE_OAUTH_TOKEN -w
#   3. .env in the repo root (fallback, see "Credentials" in docs/setup.md)
#
# Safe to run again: the profile is only imported when missing (see "Update a
# profile" in docs/customizing.md after editing one), and an existing provider
# is left alone unless --update is given. The credential is only looked up when
# it's needed, and is passed to openshell in the environment of a subshell,
# never on a command line.
set -eu

usage() { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

update=0
if [ "${1:-}" = --update ]; then update=1; shift; fi
[ $# -eq 1 ] || usage
case $1 in
  claude)   profile=claude-code-oauth; provider=claude;     var=CLAUDE_CODE_OAUTH_TOKEN; file=providers/claude-code-oauth.yaml ;;
  opencode) profile=openrouter;        provider=openrouter; var=OPENROUTER_API_KEY;      file=providers/openrouter.yaml ;;
  replicate) profile=replicate;        provider=replicate;  var=REPLICATE_API_TOKEN;  file=providers/replicate.yaml ;;
  *) usage ;;
esac

cd "$(dirname "$0")/.."

# Print the credential named $var, and on stderr where it came from.
credential() {
  value=$(printenv "$var" || true)
  if [ -n "$value" ]; then
    echo "Using $var from the environment." >&2
    printf '%s' "$value"; return
  fi
  if command -v security >/dev/null 2>&1 &&
     value=$(security find-generic-password -s openshell -a "$var" -w 2>/dev/null) && [ -n "$value" ]; then
    echo "Using $var from the Keychain." >&2
    printf '%s' "$value"; return
  fi
  if [ -f .env ]; then
    # .env holds the keys, so it must be yours and not readable or writable by anyone else.
    if [ -z "$(find .env -user "$(id -u)")" ] || [ -n "$(find .env -perm -004 -o -perm -040 -o -perm -002 -o -perm -020)" ]; then
      echo ".env must be owned by you and not readable or writable by others. Run: chmod 600 .env" >&2
      exit 1
    fi
    # Read only the one line, without running the file as shell code. Accepts
    # VAR=value, export VAR=value and single or double quotes around the value.
    value=$(sed -n "s/^\(export \)\{0,1\}$var=//p" .env | tail -n 1 | tr -d '\r' |
      sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")
    if [ -n "$value" ]; then
      echo "Using $var from .env. Prefer the Keychain, see \"Credentials\" in docs/setup.md." >&2
      printf '%s' "$value"; return
    fi
  fi
  cat >&2 <<EOF
No $var found. Store it in the Keychain (it prompts for the value):
  security add-generic-password -U -s openshell -a $var -w
or set it in the environment from your secrets manager, or put it in .env.
EOF
  exit 1
}

if openshell provider profile list 2>/dev/null | grep -qw "$profile"; then
  echo "Profile $profile already imported."
else
  openshell provider profile lint -f "$file"
  openshell provider profile import -f "$file"
fi

if openshell provider list 2>/dev/null | awk -v n="$provider" '$1==n {f=1} END {exit !f}'; then
  if [ "$update" -eq 1 ]; then
    secret=$(credential)
    (export "$var=$secret"; openshell provider update "$provider" --from-existing)
  else
    echo "Provider $provider already exists. To give it a new credential: bin/provider.sh --update $1"
  fi
else
  secret=$(credential)
  (export "$var=$secret"; openshell provider create \
    --name "$provider" --type "$profile" --from-existing)
fi
unset secret

openshell provider list
