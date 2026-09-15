# Deploy test experiments from the test branch


A full deployment test covers two experiments in `tests/deployment`:

- `tests/deployment/payment_flows_prolific`: the basic Prolific recruiter test,
  exercising payment flows (base payment, screen-out compensation, and
  performance rewards). It has a single `experiment.py`; the recruiter is
  selected via the config file. The default `config.txt` sets
  `recruiter = devprolific` (a simulated Prolific API — requests are logged,
  not sent), and the paid variant `config.txt.prolific` sets
  `recruiter = prolific`.
- `tests/deployment/audio_gibbs`: an audio Gibbs sampler experiment that
  additionally exercises audio synthesis (parselmouth), asset
  generation/storage, async worker processes, and a headphone prescreen.
  Like `payment_flows_prolific`, it has a single `experiment.py` and selects
  the Prolific recruiter via the config file (`config.txt` defaults to
  `recruiter = devprolific`; `config.txt.prolific` sets
  `recruiter = prolific`). The Lucid variant remains a separate
  `experiment.py.lucid` (with `config.txt.lucid`) because its timeline and
  Experiment class genuinely differ; the paid variants are deployed from
  temporary worktrees.

Both experiments default to `recruiter = devprolific`, which simulates the
Prolific API locally (requests are logged, not sent), so running a directory
directly cannot accidentally start paid recruitment; every paid deployment
swaps in an explicit recruiter variant first. All paid variants show the approved
cultural-foundation consent (vendored `consents_cococo` package in each
experiment directory): the Prolific variants use the `MAIN` consent and the
Lucid variant uses the `CINT` consent.

By default a full deployment test produces **three apps**: the two Prolific
experiments plus the Lucid variant of `audio_gibbs`. Overlap the long
remote image builds to save wall-clock time, but **do not start all three
`psynet deploy ssh` commands at once** (see "Stagger Local Prepare, Then
Overlap Remote Builds"). The paid `audio_gibbs` variants deploy from
temporary git worktrees; see "Prepare The Recruiter Variants".
Deploy a subset only when the user explicitly asks for it.
Prepare both experiment directories on a **single fresh deployment branch
created for this deployment** (the preparation steps below are shared).
Do not reuse or rebase a long-lived deployment branch; each deployment
gets its own branch so its exact code is preserved for later auditing.

**Base the branch on the latest PsyNet release tag by default** (including
release candidates, e.g. `v13.3.0rc0`), so the test exercises what users
actually install. Base it on `master` only when the user explicitly asks for
a master-based deployment. Always fetch tags first and confirm the chosen
base tag with the user if there is any ambiguity (e.g. an RC and a final tag
for the same version).

Deployment tests against an RC tag are the validation gate in the release
process: the `release` skill (`.cursor/skills/release/SKILL.md`) requires a
successful RC deployment test before the RC is promoted to the final
release. For RC-based deployments, end each app's `analysis.md` with an
explicit verdict line — either recommending promotion to the final release
or recommending another RC, naming the blocking findings.

Name the branch after the **PsyNet version the base commit carries**,
then the commit hash when the base is not that version's git tag.
Read the version from that commit's `pyproject.toml` (this includes
alpha versions such as `13.4.0a0`). Do **not** use
`git describe --abbrev=0` — that returns the previous *released* tag
(`v13.3.0`) and hides that the test ran on the current alpha.

```bash
PSYNET_VERSION=$(git show <base-commit>:pyproject.toml | python -c \
  "import sys, tomllib; print(tomllib.loads(sys.stdin.read())['project']['version'])")
PSYNET_TAG=v$PSYNET_VERSION
SHORT_HASH=$(git rev-parse --short=9 <base-commit>)
```

- Base **is** the git tag `v$PSYNET_VERSION`: `deployment-tests/v13.3.0rc1`
- Base is any other commit (master, a feature branch, a pin, including
  unreleased alpha): `deployment-tests/v13.4.0a0-7e0c52c31`
  (`<version-tag>-<short-hash>`)

The version tag must come **before** the hash so a later reader can see
which PsyNet version the test was run on (stable, RC, or alpha).
Do not use `master-<hash>` or `issue-<n>-<hash>` as the version-bearing
name. Append `-2`, `-3`, ... for repeat deployments from the same base.
(Older branches used `master-<hash>`, `issue-1049-<hash>`,
`v13.3.0-<hash>` on an alpha commit, or a per-experiment suffix such as
`-prolific`; new branches cover both experiments and drop the suffix.)

Before deploying:

1. Verify the deployment server is reachable before doing any preparation
   work, so connectivity problems surface immediately rather than after the
   branch and pins are already set up. Check both SSH login and the Docker
   daemon on the server:

```bash
ssh -i <ssh-key> -o BatchMode=yes -o ConnectTimeout=10 <ssh-user>@<ssh-host> \
  "docker info --format '{{.ServerVersion}}'"
```

   Success prints the server's Docker version. If the SSH login or the Docker
   check fails, stop and report the failure to the user instead of starting
   the deployment preparation.
2. Verify the recruiter credentials are set up for **both Prolific and
   Lucid** before deploying anything. The Prolific token and the Lucid
   API/hashing keys must be present (typically in `~/.dallingerconfig`);
   commented-out entries count as missing. Check presence without printing
   any values:

```bash
python - <<'PY'
from dallinger.config import get_config

config = get_config()
config.load()
for key in ["prolific_api_token", "lucid_api_key", "lucid_sha1_hashing_key"]:
    try:
        status = "set" if config.get(key) else "EMPTY"
    except KeyError:
        status = "MISSING"
    print(f"{key}: {status}")
PY
```

   If any credential is missing or empty, stop and ask the user to set it
   before deploying (a missing Lucid key otherwise only surfaces after the
   Lucid app's Docker image is already built, wasting a deploy cycle).
3. Check both repositories for local changes. Do not discard or overwrite user
   work. If either checkout is dirty in a way that affects deployment, stop and
   ask the user how to proceed.
4. Create the deployment branch from the base and import both experiment
   directories from the most recent previous deployment branch, or from
   `master` if it is newer or no previous deployment branch exists (the
   `tests/deployment` directories carry deployment settings that are
   typically not on release tags):

```bash
cd <psynet-root>
git fetch origin master --tags
BASE_COMMIT=$(git tag --list 'v*' --sort=-v:refname | head -1)  # or the commit the user specifies
PSYNET_VERSION=$(git show "$BASE_COMMIT:pyproject.toml" | python -c \
  "import sys, tomllib; print(tomllib.loads(sys.stdin.read())['project']['version'])")
PSYNET_TAG=v$PSYNET_VERSION
SHORT_HASH=$(git rev-parse --short=9 "$BASE_COMMIT")
if git rev-parse -q --verify "refs/tags/$PSYNET_TAG" >/dev/null \
  && [ "$(git rev-parse "$BASE_COMMIT")" = "$(git rev-parse "$PSYNET_TAG")" ]; then
  BASE_NAME=$PSYNET_TAG
else
  BASE_NAME=$PSYNET_TAG-$SHORT_HASH
fi
echo "Base: $BASE_NAME ($BASE_COMMIT)"
git switch -c deployment-tests/$BASE_NAME "$BASE_COMMIT"
git checkout <previous-deployment-branch> -- tests/deployment/payment_flows_prolific tests/deployment/audio_gibbs
```

   For an explicitly requested master-based deployment, update local `master`
   (`git switch master && git pull --ff-only origin master`) and branch from
   `master` instead.

   Verify the imported experiment configuration includes the standing
   deployment settings:

   - `payment_flows_prolific/config.txt`: `recruiter = devprolific` (safe
     simulated default).
   - `payment_flows_prolific/experiment.py` (shared by both recruiters):
     `prolific_is_custom_screening=False`, `auto_recruit=True`,
     `initial_recruitment_size=12`.
   - `payment_flows_prolific/config.txt.prolific`: `recruiter = prolific`.
   - `audio_gibbs/config.txt`: `recruiter = devprolific` (safe simulated
     default).
   - `audio_gibbs/experiment.py` (shared by both Prolific recruiters):
     `auto_recruit=True`, `initial_recruitment_size=3`,
     `target_n_participants=5`, `prolific_screen_out_slots` set.
     `on_launch` aborts unless the recruiter is `prolific` or
     `devprolific`.
   - `audio_gibbs/config.txt.prolific`: `recruiter = prolific`.
   - `audio_gibbs/experiment.py.lucid`: `initial_recruitment_size=10` equal to
     `target_n_participants=10`, so the Lucid survey is created with its full
     quota (the marketplace UI shows the full expected completes and fields
     to target without PsyNet-side quota top-ups). It also sets
     `wage_per_hour=18` (Lucid's `QuotaCPI` is derived from
     `estimated_max_reward(wage_per_hour)`; the default wage yielded a CPI of
     ~0.5, which converted poorly) and opens with a short plain-language
     welcome page ("4-minute listening study, headphones required, ...")
     before consent to reduce voluntary bounces at entry. The experiment
     also sets the Lucid survey to `complete` via the API once the
     participant target is reached (`Exp.recruit` override): Lucid does not
     promptly stop admitting entrants at the quota on its own, and
     `LucidRecruiter.close_recruitment` is a no-op.
   - `audio_gibbs/lucid_recruitment_config.json` carries marketplace
     qualifications that prescreen panelists before they enter PsyNet:
     desktop-only (`MS_is_mobile`/`MS_is_tablet` excluded) and audio
     capability (`HAS_AUDIO v1`). This shifts ineligible participants from
     entry bounces to marketplace screen-outs.
   - All `config.txt` files, including `config.txt.lucid`:
     `publish_experiment = true`.

5. Match Dallinger to the SHA or tag that the PsyNet base pins in
   `pyproject.toml` (a git SHA for current master/alpha pins, or a
   `vX.Y.Z` tag on a release). Do not assume a different Dallinger
   `master` tip than that pin.

```bash
cd <dallinger-root>
git fetch origin --tags
git checkout <dallinger-sha-or-tag-from-psynet-pyproject>
DALLINGER_SHA=$(git rev-parse HEAD)
```

6. Activate the PsyNet virtual environment and install both local checkouts in
   editable mode so the deployment command is run from the latest local code:

```bash
cd <psynet-root>
source <venv>/bin/activate
echo "$VIRTUAL_ENV"
uv pip install -e <dallinger-root>
uv pip install -e ".[dev,slack]"
```

7. Prepare deployable experiment boilerplate from the installed PsyNet (which
   matches the base after step 6). In-repo experiments under
   `tests/deployment/` track authored files only, so the deployment branch must
   materialize scaffold templates (Dockerfile, `deploy.toml`, `pytest.ini`,
   etc.) before deploy. Run this in **each** experiment directory being
   deployed:

```bash
for exp in payment_flows_prolific audio_gibbs; do
  (cd <psynet-root>/tests/deployment/$exp && psynet scripts update)
  # If boilerplate is missing entirely, use:
  # psynet scripts scaffold --skip-constraints
done
# Scaffold paths are gitignored under tests/deployment/; force-add so the
# deployment branch records the exact deployable tree.
git add -f tests/deployment
git commit -m "Refresh experiment scripts via psynet scripts update"
```

   Review the diff before committing; template changes should be plausible for
   the base version (e.g. pinned image tags matching the base tag).

8. Pin the packages in each experiment's `requirements.txt`
   to match the base (keep the extra `audio_gibbs` dependencies such as
   `praat-parselmouth` and `scipy` in place):

   - **Release-tag deployment (default)**: pin PsyNet to the base tag and
     Dallinger to its matching tag, e.g.

     ```text
     dallinger[docker] @ git+https://github.com/Dallinger/Dallinger.git@v12.2.1
     psynet @ git+https://gitlab.com/PsyNetDev/PsyNet.git@v13.3.0rc0
     ```

   - **Master-based deployment**: pin PsyNet to the latest pushed `master`
     commit hash, and Dallinger to the SHA that `pyproject.toml` declares.
     Never pin to a branch name; PsyNet's deploy pre-check rejects
     branch-name requirements as ambiguous.

   Commit the imported/updated experiment configuration and pins, push the
   deployment branch (for auditability), and record the base tag (or master
   commit), the deployment-branch commit, and the Dallinger pin in the final
   report.
9. Generate `constraints.txt` from the pinned `requirements.txt` in each
   experiment directory before deploying, and commit them. Authored-only
   in-repo layouts omit constraints by design; the experiment Dockerfile
   installs from `constraints.txt` when it exists, so deployable branches need
   a fresh file matching the pins:

```bash
for exp in payment_flows_prolific audio_gibbs; do
  (cd <psynet-root>/tests/deployment/$exp && psynet generate-constraints)
done
# constraints.txt is gitignored under tests/deployment/; force-add for the
# deployment-branch audit trail.
git add -f tests/deployment/*/constraints.txt
git commit -m "Generate constraints from pinned requirements"
```

10. Ensure neither experiment enables `prolific_is_custom_screening`
   (`payment_flows_prolific/experiment.py` sets it to `False`
   explicitly;
   `audio_gibbs` relies on the `False` default). Prolific no longer supports
   the older custom-screening study creation flow; a launch payload with
   `"is_custom_screening": true` fails with Prolific error `140003`.

Deploy all three apps from their own directories with their own app names:
`payment_flows_prolific` from the main checkout (after its Prolific-variant
swap is committed on the deployment branch), and the two paid `audio_gibbs`
variants from temporary worktrees (both swaps prepared as described in
"Prepare The Recruiter Variants" below). Start each deploy as a background
process (or in a separate terminal) and monitor all launch outputs, but
**stagger the starts** so only one deploy is in local prepare at a time
(see the next section). Do not background all three in one shot.

```bash
source <psynet-root>/<venv>/bin/activate

(cd <psynet-root>/tests/deployment/payment_flows_prolific && psynet deploy ssh \
  --server <ssh-host> \
  --dns-host <dns-host> \
  --app <payment-flows-prolific-app-name>) &
```

Wait until that deploy prints `Attempting to build image on remote host`
(fallback if that line is skipped: `Experiment UID:`). Then start the next:

```bash
(cd <prolific-worktree>/tests/deployment/audio_gibbs && psynet deploy ssh \
  --server <ssh-host> \
  --dns-host <dns-host> \
  --app <audio-gibbs-prolific-app-name>) &
```

Wait for the same marker, then start the third:

```bash
(cd <lucid-worktree>/tests/deployment/audio_gibbs && psynet deploy ssh \
  --server <ssh-host> \
  --dns-host <dns-host> \
  --app <audio-gibbs-lucid-app-name>) &
```

After all three have passed the marker, the remote builds overlap.

Do not let one deployment's failure silently abort the others: check each
launch output separately, and report per-app success/failure.

Name each app after the same `<base-name>` as the deployment branch
(tag, or `tag-hash`), then the experiment and recruiter:
`test-<base-name>-payment-flows-prolific` and
`test-<base-name>-audio-gibbs-prolific`, appending `-2`, `-3`, ... for
repeat deployments. App names only allow `a-z`, `0-9`, and `-` (the deploy
command rejects anything else), so replace the dots in the tag with dashes
and keep the hash after the tag:

- Tag base `v13.3.0rc1` → `test-v13-3-0rc1-payment-flows-prolific-1`
- Alpha commit `13.4.0a0` + `7e0c52c31` →
  `test-v13-4-0a0-7e0c52c31-payment-flows-prolific-1`

Never put the hash before the tag, and never omit the tag on a
commit-based app (`test-master-8ece25f0-...` and
`test-issue-1049-7e0c52c31-...` are the old forms). Because the
per-deployment folder under `deployment-tests/` is named after the app,
the archive path also shows the version. (Older deployments used
`test-<base-tag>-prolific` and `test-<base-tag>-audio-gibbs` before the
recruiter suffix became part of the convention.) After deployment, inspect
each launch output for the experiment URL, dashboard URL, and Dozzle URL.
For `audio_gibbs` variants, also run the post-launch container source check
in `recruiter-variants.md` before calling the deploy a success. A matching
   git branch is not enough: Dallinger can reuse a Docker image that still
   contains the other variant's `experiment.py`.

## Stagger Local Prepare, Then Overlap Remote Builds

Every `psynet deploy ssh` uses the **developer's local Postgres** before it
touches the remote host. `_pre_launch` calls `prepare`, which runs
`db.init_db(drop_all=True)` and `experiment.pre_deploy()` against the shared
`dallinger` database (schema create includes
`CREATE TYPE participant_status AS ENUM ...`). After that local work
finishes, the deploy no longer needs local Postgres: it builds the image
and launches on the server.

Starting two or more deploys at the same instant races that local
`init_db`. The typical failure is **not** a remote crash-loop. It dies
during local prepare with:

```text
IntegrityError / UniqueViolation
Key (typname, typnamespace)=(participant_status, 2200) already exists
CREATE TYPE participant_status AS ENUM (...)
```

`audio_gibbs` `pre_deploy` (assets / snapshot) can take longer than
`payment_flows_prolific`, so a "start all three and hope" launch often
fails the two `audio_gibbs` apps while the first one proceeds.

**Rule:** only one deploy may be in local prepare at a time. Start the
next only after the previous log shows
`Attempting to build image on remote host` (fallback: `Experiment UID:`).
From that point the expensive remote Docker builds and launches may
overlap.

If a deploy hits the `participant_status` UniqueViolation, treat it as
this local race. Leave any deploy that already passed the marker running.
Retry **only** the failed command, and only after every in-flight deploy
has printed the marker (or finished). Do not restart the whole trio at
once.

