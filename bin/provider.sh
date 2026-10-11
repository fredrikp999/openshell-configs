#!/bin/sh
# Import a provider profile and create the provider from the credentials in .env.
#
#   bin/provider.sh <claude|opencode>
#
#   bin/provider.sh claude      # profile claude-code-oauth, provider claude
#   bin/provider.sh opencode    # profile openrouter, provider openrouter
#
# Safe to run again: the profile is only imported when missing (see "Update a
# profile" in docs/customizing.md after editing one), and an existing provider
# is left alone.
# .env is loaded in a subshell, only for `provider create`.
set -eu

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

[ $# -eq 1 ] || usage
case $1 in
  claude)   profile=claude-code-oauth; provider=claude;     file=providers/claude-code-oauth.yaml ;;
  opencode) profile=openrouter;        provider=openrouter; file=providers/openrouter.yaml ;;
  *) usage ;;
esac

cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env not found. Run: cp .env.example .env, then fill it in." >&2; exit 1; }
# .env holds the keys and is run as shell code below, so it must be yours and
# not readable or writable by anyone else.
if [ -z "$(find .env -user "$(id -u)")" ] || [ -n "$(find .env -perm -004 -o -perm -040 -o -perm -002 -o -perm -020)" ]; then
  echo ".env must be owned by you and not readable or writable by others. Run: chmod 600 .env" >&2
  exit 1
fi

if openshell provider profile list 2>/dev/null | grep -qw "$profile"; then
  echo "Profile $profile already imported."
else
  openshell provider profile lint -f "$file"
  openshell provider profile import -f "$file"
fi

if openshell provider list 2>/dev/null | awk -v n="$provider" '$1==n {f=1} END {exit !f}'; then
  echo "Provider $provider already exists. To change its credential: openshell provider update $provider --help"
else
  (set -a; . ./.env; openshell provider create \
    --name "$provider" --type "$profile" --from-existing)
fi

openshell provider list
