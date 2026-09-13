---
name: branch-review
description: Review branch changes against `master` using a diff-to-master workflow that emphasizes correctness, regressions, API breaks, side effects, and missing tests. Use when the user asks to review a branch against `master`, compare branch changes, perform pre-merge code review, or review a merge request.
---

# Branch Review

Use this skill when reviewing a feature branch against `master`.

## Prerequisites

1. Verify you are not already on `master`:
   - `git rev-parse --abbrev-ref HEAD`
   - If the result is `master`, ask the user which branch to review.
2. Refresh the base branch:
   - `git fetch origin master`

## 1) Scope the change

The review scope is the committed branch diff in `origin/master...HEAD`.
Do not treat uncommitted local changes as part of the branch review.

- `git rev-parse --abbrev-ref HEAD` — confirm you are on the feature branch, not `master`
- `git diff --name-status origin/master...HEAD`
- `git diff --stat origin/master...HEAD`
- `git status --short` — if non-empty, note that uncommitted work exists locally and was not included in the review

## 2) Inspect code diffs deeply

Review behavior-changing files first, especially core code and tests.

Check for:

- correctness bugs
- regressions
- breaking API behavior
- hidden side effects such as I/O, DB, network, or CLI changes

## 3) Validate test coverage

Behavior changes should typically be covered by tests, including:

- positive paths
- error paths
- edge cases

Look for missing tests around:

- mixed or invalid types
- empty or `None` values
- filename or path normalization
- platform-specific behavior

Avoid bloated tests, though: unless the area is particularly high risk,
recommend avoiding tests that are overly complex or long compared to the original code.

## 4) Refactoring opportunities

Flag:

- repetitive code
- mixed concerns in the same function or module
- unclear naming or missing docstrings
- dead code
- compatibility shims that may no longer be needed

## 5) Verification

- Run focused tests for changed areas when practical.
- If tests cannot run, say why and state the residual risk.

## 6) Report format

Present findings first, ordered by severity.

Use this structure:

1. Findings
2. Missing tests
3. Refactoring opportunities
4. Residual risks / assumptions

Keep summaries brief and make the primary feedback actionable.

## 7) Update the merge request

Always update the open merge request title and description to match the committed
branch diff. Do this even if the current title or description looks close.

- Find the MR: `glab mr view --output json` or
  `glab api projects/PsyNetDev%2FPsyNet/merge_requests/<iid>`
  (find the IID with `glab mr list --source-branch <branch>` if needed).
- Title: a concise, accurate summary of the committed change.
- Description: follow `.gitlab/merge_request_templates/Default.md` and keep
  every section current (Motivation, Summary of changes, Behavior changes,
  Testing, Automatic code review). Compare each section against the reviewed
  diff. Look for stale claims: changes that were later reverted or reworked,
  CI/test statements that no longer hold, and new commits not yet reflected.
- Record that `/branch-review` was run in **Automatic code review**.
- If no merge request exists, say so and skip this step.
