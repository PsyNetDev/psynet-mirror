---
name: reorganize-onto-target
description: >-
  Rebuild a PsyNet feature branch as logical commits on the open GitLab
  merge-request target with git reset --soft, then force-with-lease
  push. Use just before merging the MR into its target, or when the
  user runs /reorganize-onto-target.
---

# Reorganize Onto Target

Rebuild the current feature branch as a few logical commits on the
open merge request's **target**. The point is the commit grouping, not
merely a straight-line history. `git reset --soft origin/<target>`
keeps the reviewed tree and moves `HEAD` to that target so you can
recommit in sensible units.

## When to run

Run this **just before** the MR is merged into that target. Do not run
it as part of `/branch-review`.

This skill does **not** merge. It must **not** fetch a newer target and
then soft-reset onto it: that would drop work that was never reviewed.
If `origin/<target>` is not already an ancestor of `HEAD`, stop and tell
the user to run `/update-onto-target` first.

## Resolve the target

Follow `.cursor/skills/update-onto-target/SKILL.md` (Resolve the target).

## Prerequisites

1. Confirm you are on a feature branch, not the target:
   `git rev-parse --abbrev-ref HEAD`
2. Stop if there are uncommitted changes to tracked files.
3. Confirm `git merge-base --is-ancestor origin/<target> HEAD`. If that
   fails, follow When to run.

## 1) Soft-reset onto the target

```bash
git branch "<branch>-before-rewrite" HEAD
git reset --soft "origin/$target"
```

The index and worktree stay at the reviewed merge result. `HEAD` is
now `origin/<target>`.

## 2) Recreate logical commits

Unstage if you need more than one commit (`git reset`), then `git add`
feature files in groups. Each commit should be one concern (for
example metadata, a dependency pin, CI, docs). Do not recommit the
target's own changes — they are already the parent.

One commit is fine when the change is a single unit. Prefer a few
clear commits over replaying the original incremental history.

## 3) Push

```bash
git push --force-with-lease origin HEAD
```

Never force-push the target branch. Leave the
`<branch>-before-rewrite` backup until the user is happy.
