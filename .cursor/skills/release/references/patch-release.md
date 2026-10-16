# Patch release path


Example: releasing 13.1.1 from the existing `release-13.1` branch.

### 1. Verify starting state

```bash
git checkout release-13.1
git pull origin release-13.1
git log --oneline v13.1.0..HEAD   # confirm which fixes are included
```

### 2. Prepare the release commits

Perform the shared steps, in this order:

1. [Update the CHANGELOG](shared-steps.md#update-the-changelog) — cherry-picked fixes
   carry their `changelog.d/` fragments with them; fold them into the
   patch release section. Add fragments manually for any fix that is
   missing one.
2. [Bump the version](shared-steps.md#bump-the-version) (e.g. `13.1.0` → `13.1.1`)
3. [Update What's new](shared-steps.md#update-whats-new) only if the patch has something
   experimenter-facing worth calling out
4. [Update package translations](shared-steps.md#update-package-translations) if this
   patch changed translatable PsyNet strings

### 3. Push the release branch

> **Human checkpoint:** confirm with the release manager that the local
> commits look correct before they become visible on `origin`.

```bash
git push origin release-13.1
```

### 4. Publish

Perform the shared steps, in this order:

1. [Tag the release](shared-steps.md#tag-the-release)
2. [Wait for CI to pass](shared-steps.md#wait-for-ci-to-pass) (the tag pipeline runs
   tests against the tagged commit)
3. [Build and upload to PyPI](shared-steps.md#build-and-upload-to-pypi)
4. [Verify the documentation deployment](shared-steps.md#verify-the-documentation-deployment)
5. [Create the GitLab release](shared-steps.md#create-the-gitlab-release)
6. [Announce the release on Slack](shared-steps.md#announce-the-release-on-slack)

### 5. Merge back to master (if applicable)

> **Human checkpoint:** the release manager must approve merging or
> cherry-picking release-branch fixes back into `master`.

If the fix should also appear on `master`, cherry-pick or merge the release
branch back:

```bash
git checkout master
git merge release-13.1
git push origin master
```

`master` should remain on its current alpha version (e.g. `13.2.0a0`);
restore it if the merge changed the version files.

