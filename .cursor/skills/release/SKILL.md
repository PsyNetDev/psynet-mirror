---
name: release
description: >-
  Guide a PsyNet release (major or minor from master, or patch from a
  release branch), including choosing the type from changelog fragments,
  changelog, version bump, tagging, PyPI, GitLab release, Slack, and RC
  validation. Use when cutting a PsyNet release, release candidate, or
  patch from an existing release branch.
compatibility: Requires active PsyNet venv, PyPI/twine credentials, GitLab release-manager approval at human checkpoints, and Slack announce tooling.
---

# PsyNet release process

Start by [choosing the release type](#choose-the-release-type). Do not
open a release branch, fold the changelog, or bump versions until the
release manager has affirmed the proposal. `/release major`,
`/release minor`, or `/release patch` is an override to weigh against
that proposal, not a skip of the checkpoint.

| Path | When |
| --- | --- |
| Major | Breaking changes from `master` → `references/minor-release.md` with an `X.0.0` version |
| Minor | Backwards-compatible work from `master` → `references/minor-release.md` |
| Patch | Bug fixes on `release-MAJOR.MINOR` → `references/patch-release.md` |
| RC (default for major and minor) | Pre-final validation → `references/release-candidates.md` |

Both from-master paths share `references/shared-steps.md` (changelog,
version bump, translations, tag, PyPI, GitLab release, Slack) with the
patch path. See `references/version-reference.md` for version files,
naming, and Dallinger upgrade notes.

## Choose the release type

Propose a type from the **committed** changelog fragments that would
fold into this release, plus the current branch and the last **final**
tag (ignore `rc` / `a` / `b` tags). Ignore untracked and unstaged
`changelog.d/` files; those are not in the release.

```bash
git rev-parse --abbrev-ref HEAD
grep -E '^psynet_version' psynet/version.py
git tag --list 'v[0-9]*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1
git ls-files 'changelog.d/*.md' | grep -v README | sed -E 's/.*\.([^.]+)\.md$/\1/' | sort | uniq -c
git ls-files 'changelog.d/*.breaking.md'
```

Rules, in order:

1. **Patch** if `HEAD` is already `release-MAJOR.MINOR` (or an explicit
   `/release patch` that the manager still wants after seeing the
   proposal). Version is the next patch of that series
   (`v13.3.0` → `13.3.1`). Do not cut a patch from `master`.
2. **Major** if that tree has any committed `*.breaking.md` fragments.
   Version is the next major of the last final tag (`v13.3.0` →
   `14.0.0`), branch `release-14.0`, first RC `14.0.0rc1`. Master's
   current alpha (for example `13.4.0a0`) may still name the old
   minor series; the bump commits change it.
3. **Minor** otherwise, when releasing from `master`. Version matches
   the current alpha's `MAJOR.MINOR` (`13.4.0a0` → `13.4.0`), branch
   `release-13.4`, first RC `13.4.0rc1`.

A `master` tree that only has fixes is still a **minor** (new series
from `master`), not a patch of the previous tag, unless the manager
chooses to cherry-pick onto `release-MAJOR.MINOR` instead.

Show the proposal in this shape, including a one-line reason and the
breaking fragment names when proposing major:

```text
Proposed: major 14.0.0 (branch release-14.0, first RC 14.0.0rc1)
Reason: 7 committed breaking fragments since v13.3.0; master is 13.4.0a0.
Override: /release minor would keep 13.4.0 despite Breaking Changes.
```

> **Human checkpoint:** stop here. The release manager must affirm the
> type, version, and branch (or name a different type) before any
> release-branch or version-bump work. Do not treat `/release minor`
> as affirmation when the fragments say major.

After affirmation, follow the matching path. Default to an RC for
major and minor unless the manager explicitly skips it.

## Prerequisites

- Active venv: `source .venv/bin/activate`; deps: `uv pip install -e '.[dev,slack]'`
- **Major / minor:** intended MRs merged; `master` CI green.
- **Patch:** fixes committed/cherry-picked on the release branch.
- The Dallinger dependency in `pyproject.toml` is pinned to a released
  version, not a Git reference; see `references/version-reference.md`.

### Pre-existing local changes

Ignore unstaged/untracked files already in the tree. Stage explicit paths only —
never `git add -A`. Move aside untracked `changelog.d/` fragments for unmerged work
before `psynet dev changelog release`.

## Human-in-the-loop policy

A human release manager must **explicitly approve** before:

1. Affirming the proposed release type, version, and branch
2. Pushing a release branch to `origin`
3. Creating or merging an MR
4. Pushing a release tag (triggers pipelines; hard to revoke)
5. Uploading to PyPI (permanent)
6. Creating the GitLab release (public)
7. Posting the Slack announcement to `#psynet-support`
8. Launching paid recruitment for an RC deployment test

Stop at each checkpoint marked in the reference docs; do not chain them.
