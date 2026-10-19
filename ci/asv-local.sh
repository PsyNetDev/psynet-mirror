#!/usr/bin/env bash
# Preview ASV benchmark results locally.
#
# Fetches the `benchmark-results` orphan branch from `origin` if not
# already present, mounts it as a git worktree at `.asv/results/`,
# generates a temp asv config that pins the rendered set to the current
# branch (the committed config tracks `master`), then runs `asv publish`
# and serves the rendered HTML at http://127.0.0.1:8080. Detaches the
# worktree on exit.
#
# Note: CI commits results keyed to the commits it ran on, so this only
# renders data when run from the branch those results live on.
#
# Usage: bash ci/asv-local.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="$REPO_ROOT/.asv/results"
BRANCH="benchmark-results"
REMOTE="${ASV_RESULTS_REMOTE:-origin}"
ATTACHED=0
TMP_CONF=""

# shellcheck source=ci/asv-worktree-lib.sh
source "$(dirname "$0")/asv-worktree-lib.sh"

cd "$REPO_ROOT"

cleanup() {
    detach_worktree
    if [ -n "$TMP_CONF" ]; then
        rm -f "$TMP_CONF"
    fi
}
trap cleanup EXIT

# Detach any pre-existing worktree so we can force-update the branch ref
# below. Anything inside the worktree is regenerable (asv publish only
# reads from it), so a force remove is safe.
if [ -e "$RESULTS_DIR/.git" ]; then
    git worktree remove --force "$RESULTS_DIR" 2>/dev/null || true
fi

if ! fetch_branch && ! git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "Error: $BRANCH branch not found locally or on $REMOTE" >&2
    echo "Push at least one CI run to populate it before running this script." >&2
    exit 1
fi

attach_worktree

# Temp config must live in REPO_ROOT so the relative paths in
# asv.conf.json (`repo: "."`, `env_dir`, `results_dir`, `html_dir`) all
# still resolve to the same directories the committed config uses.
TMP_CONF="$REPO_ROOT/.asv-local.conf.json"
make_current_branch_config "$TMP_CONF"

asv --config "$TMP_CONF" publish
echo
echo "Open http://127.0.0.1:8080 in your browser. Ctrl+C to stop."
asv --config "$TMP_CONF" preview
