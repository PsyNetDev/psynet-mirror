# Version and naming reference

**Pre-release check: no Git-reference Dallinger dependency.** Before
cutting any release, including a release candidate, inspect the
`dallinger[docker]` entry in `pyproject.toml`. If it points to a Git
reference, wait for the required Dallinger release and restore a versioned
specifier before publishing PsyNet.

After restoring a released dependency:

1. Refresh the vendored constraints with
   `psynet dev ci update-dallinger-constraints`.
2. Remove temporary test skips or tooling workarounds for the Git reference.
3. Update `recommended_dallinger_major_minor` in `psynet/version.py` if the
   major/minor series changed.

Do not publish PsyNet to PyPI with a direct Git dependency: PyPI rejects
direct URL dependencies, and moving branches are not reproducible.

If this release upgrades the Dallinger dependency:

- Update the Dallinger version specifier in `pyproject.toml`
  (e.g. `dallinger[docker]>=12.2.0,<13`).
- Update `recommended_dallinger_major_minor` in `psynet/version.py`.
- Refresh the vendored Dallinger CI constraints snapshot with
  `psynet dev ci update-dallinger-constraints`.
- Install the intended Dallinger version before running
  `psynet dev experiments update`, because the command uses the installed
  package when resolving constraints.

## Version files reference

The version is tracked in two files, both updated together:

- **`psynet/version.py`** — `psynet_version` variable
- **`pyproject.toml`** — `version` field under `[project]`

## Naming conventions

- Release branch: `release-MAJOR.MINOR` (e.g. `release-13.2`)
- Tag: `vMAJOR.MINOR.PATCH` (e.g. `v13.2.0`)
- Post-release bump branch: `bump-master-post-release`
- Commit messages follow the pattern seen in past releases:
  - `Update CHANGELOG for version X.Y.Z`
  - `Bump version to X.Y.Z`
