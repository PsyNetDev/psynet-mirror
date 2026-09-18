# Shared release steps


These steps are referenced from both release paths (and the RC flow). Perform
them in the order given by the path you are following.

### Update the CHANGELOG

Generate the release section from committed changelog fragments:

```bash
psynet dev changelog release X.Y.Z YYYY-MM-DD
```

This folds all fragments in `changelog.d/` into a
`# [X.Y.Z](https://gitlab.com/PsyNetDev/PsyNet/-/releases/vX.Y.Z) Release - YYYY-MM-DD`
section in `CHANGELOG.md` and removes the consumed fragments. Future changes
should add new fragment files with `psynet dev changelog new`.

Review the generated section under the appropriate categories (`## Added`,
`## Changed`, `## Fixed`, `## Removed`, `## Documentation`, etc.). Each entry
should be a user-facing sentence, without author/reviewer metadata, and should
end with a period.

Then commit. Note that `git add changelog.d` stages untracked fragments
too, so make sure any fragments belonging to unmerged work have been moved
aside first (see [Pre-existing local changes](#pre-existing-local-changes)):

```bash
git add CHANGELOG.md changelog.d
git commit -m "Update CHANGELOG for version X.Y.Z"
```

### Bump the version

Update the version string in two files:

| File | Field |
| --- | --- |
| `psynet/version.py` | `psynet_version` |
| `pyproject.toml` | `version` |

Change all occurrences from the old version to the new version. Then commit:

```bash
git add psynet/version.py pyproject.toml
git commit -m "Bump version to X.Y.Z"
```

### Update What's new

Visit `docs/whats_new/` whenever the release includes experimenter-facing
highlights or breaking changes. Add or revise the matching version page
(for example `docs/whats_new/psynet_14.rst`) and link it from
`docs/whats_new/index.rst`.

Write these pages for experiment authors: lead with what is exciting or
useful, then point clearly at any upgrade path (docs and/or
`/upgrade-to-psynet-*` skill). Do not turn them into full technical
migration manuals.

Skip this step only for patch-only releases with nothing meaningful to say
there. Commit What's new changes with the other release-preparation commits
or as their own commit on the release branch.

### Update experiment templates (no longer required)

PsyNet demos used to contain boilerplate that needed to be updated as part 
of a release, but this has been removed now, so this step is no longer necessary.

### Tag the release

> **Human checkpoint:** confirm with the release manager that the current
> release-branch commit is the intended commit to tag. Pushed tags trigger
> downstream pipelines and are awkward to revoke.

Tag the release branch commit, not `master`. This ensures the release
contains exactly the commits prepared on the release branch, even if
`master` has moved since the branch was created.

```bash
git checkout release-X.Y
git pull origin release-X.Y
git tag vX.Y.Z
git push origin vX.Y.Z
```

Pushing the tag triggers the CI test pipeline for the tagged commit. The
tag pipeline also includes the `pages` job, which builds and deploys the
documentation for the tag (see
[Verify the documentation deployment](#verify-the-documentation-deployment)).

### Wait for CI to pass

Monitor the GitLab CI pipeline for the release branch/MR/tag. **Do not
proceed until CI is green.**

Check the pipeline at:
`https://gitlab.com/PsyNetDev/PsyNet/-/pipelines`

### Verify the documentation deployment

The `pages` job in the tag pipeline builds the documentation for the
tagged version and publishes it to GitLab Pages:

- **Stable tags** (`vX.Y.Z`) are published to
  `https://psynetdev.gitlab.io/PsyNet/vX.Y.Z/`, and additionally to the
  docs root when the tag is the highest stable release.
- **Prerelease tags** (`vX.Y.ZrcN`, `vX.Y.ZaN`) are published to
  `https://psynetdev.gitlab.io/PsyNet/rc/vX.Y.ZrcN/`.

After the `pages` job has finished (Pages deployment can take a few extra
minutes after the job succeeds), verify:

1. The tag's docs URL above loads and shows the correct version number in
   the page header.
2. The new version is accessible from the version dropdown menu at
   <https://psynetdev.gitlab.io/PsyNet/>. The dropdown is driven by
   `https://psynetdev.gitlab.io/PsyNet/_static/version_switcher.json`, so
   you can also check programmatically that the JSON contains an entry
   for the tag:

   ```bash
   curl -s https://psynetdev.gitlab.io/PsyNet/_static/version_switcher.json | python3 -m json.tool
   ```

If the tag is missing from the dropdown or its docs URL 404s, inspect the
`pages` job log in the tag pipeline before proceeding to the announcement
steps.

### Build and upload to PyPI

> **Human checkpoint:** PyPI uploads are **permanent**. A version can be
> yanked but never overwritten or deleted. The release manager must
> approve both the build and the upload before either command runs.

Once CI passes, build the package and upload it to PyPI:

```bash
git checkout vX.Y.Z
rm -rf dist/ build/ *.egg-info
python -m build
twine upload dist/psynet-X.Y.Z.tar.gz dist/psynet-X.Y.Z-*.whl
rm -rf dist/ build/ *.egg-info
```

This builds both the sdist (`.tar.gz`) and wheel (`.whl`) into the `dist/`
directory, then uploads them to PyPI. The pre-build `rm -rf` ensures we
start from a clean slate; the upload glob is intentionally narrow because
`dist/psynet-X.Y.Z*` would also match leftover RC artifacts such as
`psynet-X.Y.Zrc1*`. The post-upload `rm -rf` removes generated files.

You will be prompted for PyPI credentials unless you have a `~/.pypirc`
file or a `TWINE_USERNAME` / `TWINE_PASSWORD` / `TWINE_API_KEY`
environment variable configured.

Verify the release is live at `https://pypi.org/project/psynet/X.Y.Z/`.

### Create the GitLab release

> **Human checkpoint:** the GitLab release is the public announcement
> for this version. The release manager must approve the release notes
> before publishing.

This step applies to **final releases only**. Release candidates and
other prereleases are tag-only on GitLab — see
[Release candidates](#release-candidates-minor-releases) for why.

Compose a release-notes file (e.g. `release-notes-X.Y.Z.md`) that
mirrors the corresponding section of `CHANGELOG.md` and points at the
freshly published artifacts. The body should be short — it is meant to
re-state the CHANGELOG, not duplicate it:

```markdown
## What's new in PsyNet X.Y.Z

<paste the body of the `# [X.Y.Z] Release - YYYY-MM-DD` section from
CHANGELOG.md verbatim, keeping the `## Added` / `## Changed` /
`## Fixed` / `## Removed` / `## Documentation` subheadings>

## Links

- PyPI: <https://pypi.org/project/psynet/X.Y.Z/>
- Documentation: <https://psynetdev.gitlab.io/PsyNet/>
- Full CHANGELOG: <https://gitlab.com/PsyNetDev/PsyNet/-/blob/vX.Y.Z/CHANGELOG.md>
```

The "Documentation" link points at the docs root because the highest
stable release is always served from there. Once the next release ships,
the vX.Y.Z docs will additionally be archived at
`https://psynetdev.gitlab.io/PsyNet/vX.Y.Z/` — at which point you can
update older release entries to point at that permanent URL.

#### Option A: GitLab UI

1. Open <https://gitlab.com/PsyNetDev/PsyNet/-/releases/new>.
2. Select the `vX.Y.Z` tag.
3. Set the release title to `X.Y.Z` (the version number without the
   tag's `v` prefix).
4. Paste the contents of `release-notes-X.Y.Z.md` into the
   description box.
5. Leave the **pre-release** flag **unticked** for final releases.
   (Tick it only for release candidates; see the RC flow.)
6. Click **Create release**.

#### Option B: `glab` CLI

```bash
glab release create vX.Y.Z \
  --name "X.Y.Z" \
  --notes-file release-notes-X.Y.Z.md \
  --ref vX.Y.Z
```

Verify the release is live at
`https://gitlab.com/PsyNetDev/PsyNet/-/releases/vX.Y.Z`.

### Announce the release on Slack

> **Human checkpoint:** the Slack post is broadcast to
> `#psynet-support` and cannot be unsent. The release manager must
> approve the message body before posting.

Use the `psynet dev release announce` command. It composes the message
envelope (title, RC notice, upgrade instructions, links) from the
version argument and posts using the `[slack]` extra (already installed
via the prerequisites). Set `SLACK_BOT_TOKEN` to a bot token that has
`chat:write` access to the channel. If the token is not set in the
environment and not present in the user's `~/.zshrc` or `~/.bashrc`
(check for the variable name only; never print the value), ask the user
to paste the token.

**Write the experimenter-facing summary yourself.** The command does
not generate the changes summary; you supply it via `--summary-file`.
Read the release's section in `CHANGELOG.md` (for tagged versions:
`git show vX.Y.Z:CHANGELOG.md`) and write a Slack-mrkdwn highlights
file, e.g. `/tmp/release-highlights-X.Y.Z.md`:

- Use `*Category*` headers in this order, keeping only non-empty ones:
  Breaking, Added, Changed, Deprecated, Removed, Fixed.
- One `•` bullet per entry, condensed to its essential point (drop
  leading "Added"/"Fixed", trailing rationale clauses, and author
  metadata). Use single `*` for bold and single backticks for code.
- **Include** what affects people building or running experiments:
  experiment API changes (timeline, trials, trial makers, assets,
  sync groups, modular pages), recruiter changes (Prolific/Lucid),
  anything under Breaking/Deprecated/Removed, deploy/export/debug
  command changes, translation and demo changes.
- **Exclude** maintainer-facing items: CI, tests, benchmarks, docs
  scripts, release tooling (`psynet dev` commands), Cursor skills, and
  internal refactors with no observable behavior change.
- **Add references to high-value bullets** using inline Slack links
  (`<URL|label>`):
  - Link major new features and Breaking/Deprecated/Removed items to
    the relevant documentation section. For release candidates, use
    the RC docs site (`https://psynetdev.gitlab.io/PsyNet/rc/vX.Y.ZrcN/...`)
    so links show the new behavior.
  - Link concrete class/API names to their API reference anchor whenever
    one exists, including names mentioned inside Documentation or Fixed
    bullets (e.g. `AsyncCodeBlock`, `AudioForcedChoiceTest`,
    `SyncGroup`). Check the defining module against `docs/api/` and
    confirm the anchor is present on the rendered page before linking.
  - Link new or moved demos to their directory in the repo at the tag
    (`https://gitlab.com/PsyNetDev/PsyNet/-/tree/vX.Y.Z/demos/...`),
    and also to the demo's docs page when one exists (check
    `docs/demos/` for a matching `.rst`).
  - Link to external sources when a change is driven by a third-party
    platform — e.g. a Prolific or Lucid announcement or documentation
    page explaining an API change that motivated a removal or new
    behavior.
  - Do not link every bullet — small fixes need no reference.
  - **Verify each URL resolves** (e.g. `curl -sI -o /dev/null
    -w '%{http_code}' <url>`) before posting; a 404 in an announcement
    is worse than no link.

Then preview and post:

```bash
psynet dev release announce X.Y.Z --summary-file /tmp/release-highlights-X.Y.Z.md --dry-run
psynet dev release announce X.Y.Z --summary-file /tmp/release-highlights-X.Y.Z.md --channel testing-bot-messages
psynet dev release announce X.Y.Z --summary-file /tmp/release-highlights-X.Y.Z.md
```

The dry run prints the exact body that would be posted; have the
release manager check the summary against the CHANGELOG section for
missing or superfluous bullets. Then post to the
`#testing-bot-messages` channel, so the release manager can review the
actual Slack rendering (link previews, mrkdwn formatting, block layout)
before the real announcement; only after that review post to
`#psynet-support`. The message uses Slack `mrkdwn` syntax (single `*`
for bold, `<URL|label>` for inline links); the final-release template
looks like:

```text
*:tada: PsyNet X.Y.Z is out*

• <https://gitlab.com/PsyNetDev/PsyNet/-/releases/vX.Y.Z|Release notes>
• <https://pypi.org/project/psynet/X.Y.Z/|PyPI>
• <https://psynetdev.gitlab.io/PsyNet/|Documentation>

Upgrade with `pip install --upgrade psynet`.
```

If you would rather post manually, copy the dry-run output verbatim
into a message in `#psynet-support`.

