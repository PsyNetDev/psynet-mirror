---
name: release
description: Guide a PsyNet release (minor from master or patch from a release branch), including changelog, version bump, tagging, PyPI, GitLab release, Slack, and RC validation. Use when cutting a PsyNet release, release candidate, or patch from an existing release branch.
compatibility: Requires active PsyNet venv, PyPI/twine credentials, GitLab release-manager approval at human checkpoints, and Slack announce tooling.
---

# PsyNet release process

Invoke with the release type (`/release minor` or `/release patch`). If omitted,
ask which applies.

| Path | When |
| --- | --- |
| Minor | New backwards-compatible features from `master` → `references/minor-release.md` |
| Patch | Bug fixes on `release-MAJOR.MINOR` → `references/patch-release.md` |
| RC (default for minor) | Pre-final validation → `references/release-candidates.md` |

Both paths share `references/shared-steps.md` (changelog, version bump,
translations, tag, PyPI, GitLab release, Slack). See
`references/version-reference.md` for version files, naming, and Dallinger
upgrade notes.

## Prerequisites

- Active venv: `source .venv/bin/activate`; deps: `uv pip install -e '.[dev,slack]'`
- **Minor:** intended MRs merged; `master` CI green.
- **Patch:** fixes committed/cherry-picked on the release branch.
- The Dallinger dependency in `pyproject.toml` is pinned to a released
  version, not a Git reference; see `references/version-reference.md`.

### Pre-existing local changes

Ignore unstaged/untracked files already in the tree. Stage explicit paths only —
never `git add -A`. Move aside untracked `changelog.d/` fragments for unmerged work
before `psynet dev changelog release`.

## Human-in-the-loop policy

A human release manager must **explicitly approve** before:

1. Pushing a release branch to `origin`
2. Creating or merging an MR
3. Pushing a release tag (triggers pipelines; hard to revoke)
4. Uploading to PyPI (permanent)
5. Creating the GitLab release (public)
6. Posting the Slack announcement to `#psynet-support`

Stop at each checkpoint marked in the reference docs; do not chain them.
