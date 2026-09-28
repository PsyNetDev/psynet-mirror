---
name: update-onto-target
description: >-
  Merge this branch's GitLab merge-request target into the feature
  branch and resolve every conflict. Use for /update-onto-target,
  updating onto master when that is the MR target, or as the first
  step of PsyNet /branch-review.
---

# Update Onto Target

Merge the current remote copy of this branch's merge-request **target**
into the feature branch and resolve every conflict. This is a write, not
a review, and it does **not** rewrite history.

The target is the branch the MR will merge into, not always `master`.
The open MR is the source of truth. The tree after this command is what
will land.

## Resolve the target

Stay on the feature branch. Read `target_branch` from the open MR for
this source branch and assign it to `target`. Later steps use that
variable (`git fetch origin "$target:$target"`, `git merge "origin/$target"`).

```bash
branch="$(git rev-parse --abbrev-ref HEAD)"
target="$(glab api "projects/PsyNetDev%2FPsyNet/merge_requests?source_branch=${branch}&state=opened" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data[0]['target_branch'] if isinstance(data, list) and data else '')
")"
```

If `target` is empty, there is no open MR: stop and ask which target to
use. Do not assume `master`. `glab mr view --output json` is fine if it
returns JSON and you still assign `target` from `target_branch`.

## Prerequisites

1. Confirm you are on a feature branch, not the target:
   `git rev-parse --abbrev-ref HEAD`
2. Refresh the remote and local target without checking it out:

   ```bash
   git fetch origin "$target:$target"
   ```

   That updates `origin/<target>` and fast-forwards local `<target>`.
   Stay on the feature branch. If the fetch fails because local
   `<target>` has diverged, run `git fetch origin "$target"` only,
   leave the local target branch alone, merge `origin/<target>` into
   this branch, and tell the user the local target was not moved.
3. Stop if there are uncommitted changes to tracked files. Untracked
   files may stay in the worktree.

If `git merge-base --is-ancestor origin/<target> HEAD` already
succeeds, say so and stop. The branch already contains the current
target.

## Merge the target

```bash
git merge "origin/$target"
```

Resolve every conflict. Do not abort because files conflict. The result
must be the intended combination of this branch and the target. Complete
the merge commit. If a conflict is a product decision you cannot make,
stop and ask the user; do not leave the merge half-finished.

Push the merge with a regular `git push`. Never force-push the target
branch.

If this skill was invoked on its own, typical next step is
`/branch-review`. To rewrite history onto the target, follow
`.cursor/skills/reorganize-onto-target/SKILL.md` (When to run) instead
of soft-resetting here.
