#!/usr/bin/env bash
# Prune ASV result files from the `benchmark-results` orphan branch.
#
# Selectors (combinable):
#   --machine <name>   remove results from this machine
#   --commit <hash>    remove results for this commit hash (repeatable, prefix match)
#   --dry-run          list files that would be removed, make no changes
#
# At least one of --machine or --commit is required.
# Push manually after pruning: `git push <remote> benchmark-results`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="$REPO_ROOT/.asv/results"
BRANCH="benchmark-results"
ATTACHED=0

# shellcheck source=ci/asv-worktree-lib.sh
source "$(dirname "$0")/asv-worktree-lib.sh"

MACHINE=""
COMMITS=()
DRY_RUN=0

usage() {
    sed -n '2,/^set /p' "$0" | sed '/^set /d; s/^# \{0,1\}//' >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --machine)
            [ $# -ge 2 ] || { echo "--machine requires a value" >&2; exit 1; }
            MACHINE="$2"
            shift 2
            ;;
        --commit)
            [ $# -ge 2 ] || { echo "--commit requires a value" >&2; exit 1; }
            COMMITS+=("$2")
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage
            exit 1
            ;;
    esac
done

if [ -z "$MACHINE" ] && [ ${#COMMITS[@]} -eq 0 ]; then
    echo "Error: at least one of --machine or --commit is required" >&2
    usage
    exit 1
fi

cd "$REPO_ROOT"

git config user.email >/dev/null || { echo "git user.email not set" >&2; exit 1; }
git config user.name >/dev/null || { echo "git user.name not set" >&2; exit 1; }

if ! git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "Error: local branch '$BRANCH' does not exist (run ci/asv-sync-results.sh --init-only first)" >&2
    exit 1
fi

trap detach_worktree EXIT
attach_worktree

cd "$RESULTS_DIR"

machines=()
if [ -n "$MACHINE" ]; then
    if [ ! -d "$MACHINE" ]; then
        echo "Error: no machine directory '$MACHINE' on $BRANCH" >&2
        exit 1
    fi
    machines=("$MACHINE")
else
    for d in */; do
        [ -d "$d" ] || continue
        machines+=("${d%/}")
    done
fi

to_delete=()
if [ ${#COMMITS[@]} -eq 0 ]; then
    for m in "${machines[@]}"; do
        to_delete+=("$m")
    done
else
    for m in "${machines[@]}"; do
        for hash in "${COMMITS[@]}"; do
            short="${hash:0:8}"
            while IFS= read -r f; do
                to_delete+=("$f")
            done < <(find "$m" -maxdepth 1 -type f -name "${short}*.json" 2>/dev/null)
        done
    done
fi

if [ ${#to_delete[@]} -eq 0 ]; then
    echo "No matching results to prune"
    exit 0
fi

echo "Files to remove:"
printf '  %s\n' "${to_delete[@]}"

if [ "$DRY_RUN" = "1" ]; then
    echo "(dry run — no changes made)"
    exit 0
fi

for path in "${to_delete[@]}"; do
    git rm -r -- "$path" >/dev/null
done

PRE_COMMIT_ALLOW_NO_CONFIG=1 git commit -m "asv: prune results ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
echo "Pruned ${#to_delete[@]} path(s). Push with: git push <remote> $BRANCH"
