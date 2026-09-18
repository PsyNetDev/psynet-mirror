# Minor release path


Example: releasing 13.2.0 from `master` while `master` is at `13.2.0a0`.

**Default to a release candidate first.** For minor releases, cut an RC
(e.g. `13.2.0rc1`) before the final version, unless the release manager
explicitly instructs otherwise. After creating the release branch (step 1
below), switch to the [release candidate flow](#release-candidates-minor-releases)
instead of continuing with steps 2–7; return to the final-release steps via
[Promote the final RC to the official release](#promote-the-final-rc-to-the-official-release)
once the RC has been validated.

### 1. Create the release branch

Create a new release branch from `master`. The branch name uses
`MAJOR.MINOR` (without the patch number):

```bash
git checkout master
git pull origin master
git checkout -b release-13.2
```

### 2. Prepare the release commits

Perform the shared steps, in this order:

1. [Update the CHANGELOG](#update-the-changelog)
2. [Bump the version](#bump-the-version) (from the alpha version, e.g.
   `13.2.0a0` → `13.2.0`)
3. [Update What's new](#update-whats-new) when the release has
   experimenter-facing highlights or breaking changes

### 3. Push the release branch

> **Human checkpoint:** confirm with the release manager that the
> local commits (CHANGELOG and version bump) look
> correct before the release branch becomes visible on `origin`.

```bash
git push --set-upstream origin release-13.2
```

### 4. Create a merge request

> **Human checkpoint:** the release manager must approve the MR title,
> description, and target branch before it is opened on GitLab.

Create an MR on GitLab to merge the release branch into `master`, but
**do not merge it yet**. The final release tag must be created from the
release branch, not from a later merge commit on `master`, because `master`
may have gained additional changes after the release branch was created.

- **Title:** `Release version 13.2.0`
- **Label:** apply the `Release` label, either at creation
  (`glab mr create ... --label Release`) or afterwards
  (`glab mr update <iid> --label Release`).
- Review the changes one last time in the MR "Changes" tab.
- Use a **merge commit** (do not squash), so the individual release commits
  are preserved on `master`.
- Disable source-branch deletion. Release branches are long-lived maintenance
  branches and must remain available after they are merged back into `master`.

### 5. Publish

Perform the shared steps, in this order:

1. [Wait for CI to pass](#wait-for-ci-to-pass)
2. [Tag the release](#tag-the-release)
3. [Build and upload to PyPI](#build-and-upload-to-pypi)
4. [Verify the documentation deployment](#verify-the-documentation-deployment)
5. [Create the GitLab release](#create-the-gitlab-release)
6. [Announce the release on Slack](#announce-the-release-on-slack)

### 6. Merge the release branch back into master

> **Human checkpoint:** even after the release has been tagged and
> published, the release manager must explicitly approve merging the
> release branch back into `master`.

Merge the release MR via the GitLab interface using a **merge commit** (not
squash), and make sure the source branch is not deleted. This carries forward
release bookkeeping such as the finalized `CHANGELOG.md` and version bump.
It is not the commit that should be tagged
for the release.

#### Resolving merge conflicts on the release MR

If `master` has moved since the release branch was cut, the release MR may
report merge conflicts (typically in version files). **Do not resolve them by
merging `master` into the release
branch.** That pulls every unreleased `master` change onto the release
branch, polluting it as the base for future patch releases (a later
`X.Y.1` would silently include unvalidated work).

If such a merge does land on the release branch anyway, repair it after
the release MR has merged: the merge commit is preserved on `master`, so
the release branch can safely be reset to the release tag
(`git checkout release-X.Y && git reset --hard vX.Y.Z &&
git push --force origin release-X.Y`), restoring a clean patch base.
This force push needs explicit release-manager approval.

Instead, resolve conflicts without contaminating the release branch —
for example, merge the release branch into `master` locally, resolve the
conflicts there (keeping the pinned release versions; the post-release
alpha bump re-points `master`'s copies at `master` again), and push that
merge commit to `master` in place of the MR-button merge.

#### Verify fragments after the merge-back

After the release MR has merged, check `changelog.d/` on `master` for
**resurrected fragments**. Fragments that were cherry-picked onto the
release branch and consumed there by the CHANGELOG fold exist on both
sides but were created after the branch point, so git's merge treats the
`master` copies as new additions and keeps them — leaving fragments on
`master` whose text is already in the released CHANGELOG section. If the
next release folds them again, the entries are duplicated.

Check each remaining fragment against the just-released section:

```bash
for f in changelog.d/*.md; do
  [ "$(basename "$f")" = "README.md" ] && continue
  snippet=$(head -c 60 "$f")
  if awk '/^## \[X.Y.Z\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md \
      | grep -qF "$snippet"; then
    echo "DUPLICATE: $f"
  fi
done
```

Delete any duplicates on `master` in a small follow-up commit. Fragments
that do not appear in the released section are genuinely unreleased and
must stay for the next release.

### 7. Bump master to the next alpha

After the release branch has been merged back into `master`, bump `master`
to the next development version:

```bash
git checkout master
git pull origin master
git checkout -b bump-master-post-release
```

Update the version in both version files from `13.2.0` to `13.3.0a0`.
New changes on `master` should be recorded as fragments in `changelog.d/`.

Then commit the version bump and open a MR:

```bash
git add -A
git commit -m "Bump version to 13.3.0a0"
git push --set-upstream origin bump-master-post-release
```

- **Title:** `Bump version to 13.3.0a0`
- **Description**, substituting the just-released version for `13.2.0`
  and the next development version for `13.3.0a0`:

  > Post-release bump after the 13.2.0 release: sets `master` to the next
  > development version `13.3.0a0`.

> **Human checkpoint:** the release manager must approve the
> `bump-master-post-release` MR before it is merged.

Merge this MR promptly before any new feature branches land, so the version
on `master` stays aligned with the CHANGELOG.

Unlike release branches, **delete `bump-master-post-release` when the MR
merges** (e.g. create the MR with `remove_source_branch=true`). It is a
throwaway vehicle for the two bookkeeping commits, recreated from fresh
`master` each cycle; a stale leftover from the previous cycle otherwise
forces the next release to force-push over it.

