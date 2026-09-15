# Release candidates


Publishing one or more release candidates (RCs) from the release branch
before the final tag is the **default** for minor releases; skip straight
to the final version only when the release manager explicitly instructs
otherwise. RCs are tagged and uploaded to PyPI but are **not** merged back
into `master` until the final release.

The human checkpoints from the
[Human-in-the-loop policy](#human-in-the-loop-policy) apply at the
equivalent points: pushing the release branch, pushing the RC tag,
uploading the RC to PyPI, and posting the Slack announcement.

RCs are **tag-only** on GitLab: do **not** create a GitLab release entry
for them. GitLab has no pre-release flag (unlike GitHub), so an RC
release entry would become the project's "latest release" (permalink,
releases feed, and badge) until the final version ships. This tag-only
convention matches what major GitLab-hosted projects (GitLab Runner,
Inkscape, Wireshark) do. The RC's changelog section, PyPI page, and docs
build carry all the information testers need.

Number release candidates starting from **rc1** (`13.2.0rc1`, `13.2.0rc2`,
…), matching the common convention across major projects. (Releases up to
13.3.0 started at `rc0`.)

RCs are especially valuable when:

- The release contains risky or far-reaching changes (e.g. a Dallinger
  upgrade, schema migrations, recruitment-flow changes).
- You want to give experimenters a chance to validate against their own
  studies before the final tag.
- CI is green but you want soak time on real deployments.

### RC1: Cut the first release candidate

Start from the release branch created in step 1 of the minor release path.
Instead of bumping straight to `13.2.0`, bump to `13.2.0rc1` and tag it,
using the shared steps with the RC version:

1. [Update the CHANGELOG](#update-the-changelog) with
   `psynet dev changelog release 13.2.0rc1 YYYY-MM-DD`. This creates a
   `# [13.2.0rc1](...) Release candidate - YYYY-MM-DD` section. If further
   changes land before the next RC or final release, record them as new
   fragments in `changelog.d/`.
2. [Bump the version](#bump-the-version) from `13.2.0a0` to `13.2.0rc1`.
3. [Update What's new](#update-whats-new) for experimenter-facing highlights
   or breaking changes (usually on the first RC of a minor/major).
4. Push the release branch and tag the RC. RC tags are pushed directly from
   the release branch — there is **no MR** and **no merge to `master`** at
   this stage:

   ```bash
   git push --set-upstream origin release-13.2
   git tag v13.2.0rc1
   git push origin v13.2.0rc1
   ```

   Wait for the tag pipeline to pass on GitLab.
6. [Build and upload to PyPI](#build-and-upload-to-pypi) using the RC
   version. Since the pre-build `rm -rf` guarantees a clean `dist/`, the
   broader glob `dist/psynet-13.2.0rc1*` is safe here. RCs are not marked
   as the latest release on PyPI, so users must opt in with
   `pip install psynet==13.2.0rc1`.
7. [Verify the documentation deployment](#verify-the-documentation-deployment):
   confirm that `https://psynetdev.gitlab.io/PsyNet/rc/v13.2.0rc1/` loads
   and that the RC appears in the version dropdown at
   <https://psynetdev.gitlab.io/PsyNet/>.
8. **Skip the GitLab release entry.** RCs are tag-only on GitLab (see
   above); the [Create the GitLab release](#create-the-gitlab-release)
   step applies to final releases only.
9. [Announce the release on Slack](#announce-the-release-on-slack) with the
   RC version, writing the highlights file from the RC's CHANGELOG
   section as described there. `psynet dev release announce 13.2.0rc1
   --summary-file ...` auto-detects the `rc` segment and generates an
   RC-flavoured envelope with the `/rc/<tag>/` docs URL, the
   CHANGELOG-at-tag link (since there is no GitLab release entry), and
   the opt-in install instruction:

   ```text
   *:test_tube: PsyNet 13.2.0rc1 (release candidate) is out*

   • <https://gitlab.com/PsyNetDev/PsyNet/-/blob/v13.2.0rc1/CHANGELOG.md|Release notes>
   • <https://pypi.org/project/psynet/13.2.0rc1/|PyPI>
   • <https://psynetdev.gitlab.io/PsyNet/rc/v13.2.0rc1/|Documentation>

   Opt in with `pip install psynet==13.2.0rc1`. Please test against your
   studies and report any regressions before the final tag.
   ```

   Tag any specific people whose feedback you need on a thread under the
   post rather than `@channel`-ing the whole channel.
10. **Validate the RC with a deployment test.** Run the deployment test
   suite against the RC tag by following the `deployment-test` skill
   (`.cursor/skills/deployment-test/SKILL.md`): by default this deploys
   the two Prolific test experiments (`payment_flows_prolific` and
   `audio_gibbs`) in parallel plus the `audio_gibbs` Lucid variant. The
   skill's default flow — basing the deployment branch on the latest
   release tag, including RCs — is designed for exactly this step. The
   test produces an `analysis.md` per app under `deployment-tests/`
   (not committed to PsyNet; archived in the private
   `computational-audition-lab/psynet-deployment-tests` repository); their
   verdicts feed the promotion decision below.

### Iterate: RC2, RC3, …

While the RC is being tested, additional fixes may need to land on the
release branch. Prefer to land the fix on `master` first via a normal MR,
then cherry-pick it onto the release branch:

```bash
git checkout master
git pull origin master
# fix lands on master via a normal MR (or directly if appropriate)

git checkout release-13.2
git pull origin release-13.2
git cherry-pick <commit-sha>
git push origin release-13.2
```

If a fix only makes sense on the release branch (e.g. a release-only
revert), commit it directly on `release-13.2` and remember to port it
back to `master` later if needed.

When you have enough fixes to justify another candidate, cut the next RC by
repeating the RC1 sequence with the next RC number (e.g. `13.2.0rc2`):
CHANGELOG, version bump, demo update, then push, tag, upload, and
announcement, with the same human checkpoints. Repeat for `rc3`, `rc4`,
etc. until you are confident the release is ready.

### Promote the final RC to the official release

Validation of an RC means at minimum one successful deployment test of the
RC tag via the `deployment-test` skill, with `analysis.md` files
(one per deployed app under `deployment-tests/`) whose verdicts recommend
promotion (see step 9 of the RC sequence). If the deployment test surfaced
bugs, fix them and cut another RC instead. Record a link to the
deployment-test branch and to the archived `analysis.md` files in the
`computational-audition-lab/psynet-deployment-tests` repository in the
release MR description.

Once the latest RC has been validated and no further changes are needed:

1. Consolidate the RC headings in `CHANGELOG.md` into a single final
   `# [13.2.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.2.0) Release - YYYY-MM-DD`
   section. If there are final-release fragments for changes since the latest
   RC, first run:

   ```bash
   psynet dev changelog release 13.2.0 YYYY-MM-DD
   ```

   Then review the generated/folded section and remove any now-empty
   intermediate RC headings.

2. [Bump the version](#bump-the-version) from `13.2.0rcN` to `13.2.0`.

3. Resume the minor release path from
   [step 4 (Create a merge request)](#4-create-a-merge-request) onwards
   to review the release MR, tag `v13.2.0` from the release branch,
   publish to PyPI, create the GitLab release, announce on Slack, and
   then merge the release branch back into `master`.

