#!/bin/sh
# Move code in and out of a sandbox with git bundles. The sandbox never gets
# git credentials or access to your git host.
#
#   ./bundle.sh in  <sandbox> <repo> [--branch NAME] [--base BRANCH]
#   ./bundle.sh out <sandbox> <repo> [--branch NAME] [--base BRANCH] [--force]
#
#   ./bundle.sh in  my-task ./myrepo    # repo into /sandbox/myrepo, branch agent/my-task
#   ./bundle.sh out my-task ./myrepo    # the agent's commits back as branch agent/my-task
#
# in:  bundles all branches of <repo> and uploads them. The first time, the repo
#      is cloned to /sandbox/<repo-name> and the work branch is created from
#      <base>. Later runs fetch the new commits into host/* (e.g. host/main)
#      without touching the work branch; merge or rebase them inside if needed.
# out: bundles the commits on the work branch that are not in host/<base>,
#      downloads them and fetches them into <repo> as the same branch. Review
#      them, then push and open the MR yourself. --force overwrites the branch
#      on the host if it has diverged (e.g. after a rebase in the sandbox).
#
# Defaults: --branch agent/<sandbox>, --base main.
# Requires git in the image (both images in this repo have it).
set -eu

usage() { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

[ $# -ge 3 ] || usage
cmd=$1 sandbox=$2 repo=$3
shift 3
branch=agent/$sandbox
base=main
force=false
while [ $# -gt 0 ]; do
  case $1 in
    --branch) branch=$2; shift 2 ;;
    --base) base=$2; shift 2 ;;
    --force) force=true; shift ;;
    *) usage ;;
  esac
done

git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || { echo "$repo is not a git repository." >&2; exit 1; }
name=$(basename "$(cd "$repo" && pwd)")
remote_repo=/sandbox/$name
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Run a command, and show its output only if it fails.
quiet() {
  "$@" >"$tmp/log" 2>&1 || { cat "$tmp/log" >&2; exit 1; }
}

# Run a shell script in the sandbox, with arguments ($1, $2, ...) passed safely.
in_sandbox() {
  script=$1; shift
  openshell sandbox exec "$sandbox" --no-tty -- sh -c "$script" sh "$@"
}

case $cmd in
  in)
    git -C "$repo" rev-parse --verify --quiet "refs/heads/$base" >/dev/null ||
      { echo "Branch $base doesn't exist in $repo. Use --base." >&2; exit 1; }
    bundle=$name-in.bundle
    echo "Bundling $repo (all branches)..."
    git -C "$repo" bundle create "$tmp/$bundle" --branches 2>/dev/null
    echo "Uploading to $sandbox..."
    quiet openshell sandbox upload "$sandbox" "$tmp/$bundle" /sandbox
    in_sandbox '
      set -e
      bundle=/sandbox/$1 repo=$2 branch=$3 base=$4 sandbox=$5
      if [ ! -d "$repo/.git" ]; then
        git init -q "$repo"
        cd "$repo"
        git fetch -q "$bundle" "+refs/heads/*:refs/remotes/host/*"
        git config user.name "Agent ($sandbox)"
        git config user.email "agent@$sandbox.sandbox"
        git checkout -q -b "$branch" "host/$base"
        echo "Cloned into $repo, on new branch $branch (from $base)."
      else
        cd "$repo"
        git fetch -q "$bundle" "+refs/heads/*:refs/remotes/host/*"
        echo "Fetched the latest commits into host/* in $repo."
        echo "Current branch: $(git branch --show-current). Merge or rebase host/$base if needed."
      fi
      rm -f "$bundle"
    ' "$bundle" "$remote_repo" "$branch" "$base" "$sandbox"
    ;;

  out)
    bundle=$name-out.bundle
    in_sandbox '
      set -e
      repo=$1 branch=$2 base=$3 bundle=/sandbox/$4
      cd "$repo"
      git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null ||
        { echo "Branch $branch does not exist in $repo." >&2; exit 1; }
      if [ -n "$(git status --porcelain)" ]; then
        echo "Warning: $repo has uncommitted changes. Only commits are taken out." >&2
      fi
      count=$(git rev-list --count "host/$base..$branch")
      if [ "$count" -eq 0 ]; then
        echo "No new commits on $branch (compared with $base)." >&2
        exit 3
      fi
      git bundle create -q "$bundle" "$branch" "^host/$base"
      echo "Bundled $count commit(s) from $branch."
    ' "$remote_repo" "$branch" "$base" "$bundle" || {
      status=$?
      [ $status -eq 3 ] && exit 0
      exit $status
    }
    quiet openshell sandbox download "$sandbox" "/sandbox/$bundle" "$tmp/"
    in_sandbox 'rm -f "/sandbox/$1"' "$bundle"
    plus=
    $force && plus=+
    if ! git -C "$repo" fetch -q "$tmp/$bundle" "$plus$branch:$branch" 2>"$tmp/err"; then
      cat "$tmp/err" >&2
      echo "Could not update $branch in $repo. If it is checked out there, switch to another branch." >&2
      echo "If the branch has diverged (e.g. after a rebase in the sandbox), run again with --force." >&2
      exit 1
    fi
    echo "Fetched into $repo as branch $branch:"
    git -C "$repo" log --oneline "$base..$branch"
    git -C "$repo" diff --stat "$base...$branch"
    echo
    echo "Review:   git -C $repo diff $base...$branch"
    echo "Push:     git -C $repo push origin $branch"
    ;;

  *) usage ;;
esac
