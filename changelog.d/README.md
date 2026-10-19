# Changelog Fragments

Add one changelog fragment per change in this directory. The recommended
way to create one is:

```bash
psynet dev changelog new <category> "<short description>"
```

This writes a uniquely-named fragment file containing your description as a
stub, which you then edit to the final entry.

## Filename format

`<YYYYMMDD-slug>.<category>.md`

The date prefix keeps fragments roughly chronological and the slug
differentiates same-day fragments. `psynet dev changelog new` creates
this format automatically and refuses to overwrite an existing file, so
use a more specific description if it complains. Hand-rolled fragment
names are valid only if they follow the same date-prefixed format.

Supported categories (rendered in this order):

- `breaking` → **Breaking Changes**
- `added` → **Added**
- `changed` → **Changed**
- `deprecated` → **Deprecated**
- `removed` → **Removed**
- `fixed` → **Fixed**
- `updated` → **Updated**
- `documentation` → **Documentation**

Fragment contents should be a single changelog entry in markdown without a
leading `-`.

Examples:

- `20260513-add-chatroom-demo.added.md`
- `20260513-fix-selenium-flake.fixed.md`
- `20260514-deprecate-old-helper.deprecated.md`

## Workflow

Contributors commit **only** the fragment file in their MR, never a
regenerated `CHANGELOG.md`. `CHANGELOG.md` is a generated artifact and
contains released sections only;
committing it from MRs would re-introduce the merge-conflict problem
that fragments are designed to prevent.

If you want to preview how your fragment will render, run the command
from a PsyNet source checkout. It prints the rendered fragment sections
to stdout and leaves `CHANGELOG.md` unchanged:

```bash
psynet dev changelog preview
```

Maintainers cut a release from the current fragments from a PsyNet source
checkout with:

```bash
psynet dev changelog release 13.2.0 2026-03-13
```

This inserts a new `## [13.2.0]` section and deletes the consumed
fragments. Beta and release-candidate versions also insert normal
versioned sections. Alpha versions (e.g. `13.2.0a0`) do not get
changelog release sections; keep fragments until the first release
candidate or stable release. Stable releases consume all matching beta
and release-candidate sections (e.g. `13.2.0b0`, `13.2.0rc1`) plus any
remaining fragments so the final release notes are complete.

## Direct pushes to `master`

The `changelog_check` CI job only runs on merge requests, so it cannot
catch missing fragments on direct pushes to `master`. If you push
directly to `master` (bypassing an MR), please still create a fragment
with `psynet dev changelog new` so the change appears in the next
release notes. Its date-prefixed filenames stay unique as long as slugs
differ on the same day.

## Migrated fragments

The historical in-progress changelog block was migrated into date-prefixed
fragments using commit-history dates and descriptive slugs. These remain
valid and will be consumed at the next release. Please use
`psynet dev changelog new` for all new fragments going forward.
