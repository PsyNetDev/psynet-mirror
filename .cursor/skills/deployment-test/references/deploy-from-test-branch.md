# Deploy test experiments from the test branch


A full deployment test covers two experiments in `tests/deployment`:

- `tests/deployment/payment_flows_prolific`: the basic Prolific recruiter test,
  exercising payment flows (base payment, screen-out compensation, and
  performance rewards). Its default `experiment.py` uses HotAir; the paid
  variant lives in `experiment.py.prolific` (with `config.txt.prolific`).
- `tests/deployment/audio_gibbs`: an audio Gibbs sampler experiment that
  additionally exercises audio synthesis (parselmouth), asset
  generation/storage, async worker processes, and a headphone prescreen.
  Its default `experiment.py` also uses HotAir. Prolific and Lucid variants
  (`experiment.py.prolific` and `experiment.py.lucid`, with matching config
  files) are deployed from temporary worktrees.

Both experiments default to HotAir so running a directory directly cannot
accidentally start paid recruitment; every paid deployment swaps in an
explicit recruiter variant first. All paid variants show the approved
cultural-foundation consent (vendored `consents_cococo` package in each
experiment directory): the Prolific variants use the `MAIN` consent and the
Lucid variant uses the `CINT` consent.

By default a full deployment test produces **three apps**: the two Prolific
experiments plus the Lucid variant of `audio_gibbs`, all deployed **in
parallel** to save wall-clock time (the paid `audio_gibbs` variants deploy
from temporary git worktrees; see "Prepare The Recruiter Variants").
Deploy a subset only when the user explicitly asks for it.
Prepare both experiment directories on a **single fresh deployment branch
created for this deployment** (the preparation steps below are shared), then run the three
`psynet deploy ssh` commands concurrently. Do not reuse or rebase a
long-lived deployment branch; each deployment gets its own branch so its
exact code is preserved for later auditing.

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

Name the branch after the base, e.g. `deployment-tests/v13.3.0rc1`,
appending `-2`, `-3`, ... for repeat deployments from the same base. For a
master-based deployment, name it after `master` plus the short commit hash
it was cut from, e.g. `deployment-tests/master-8ece25f0`, so master-based
test deployments are clearly distinguishable from release-tag ones and
from each other. (Older deployment branches carry a per-experiment suffix
such as `-prolific`; new branches cover both experiments and drop it.)

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
BASE_TAG=$(git tag --list 'v*' --sort=-v:refname | head -1)  # or the tag the user specifies
echo "Base: $BASE_TAG"
git switch -c deployment-tests/$BASE_TAG "$BASE_TAG"
git checkout <previous-deployment-branch> -- tests/deployment/payment_flows_prolific tests/deployment/audio_gibbs
```

   For an explicitly requested master-based deployment, update local `master`
   (`git switch master && git pull --ff-only origin master`) and branch from
   `master` instead.

   Verify the imported experiment configuration includes the standing
   deployment settings:

   - `payment_flows_prolific/experiment.py`: recruiter `hotair` (safe local
     default).
   - `payment_flows_prolific/experiment.py.prolific`:
     `prolific_is_custom_screening=False`, `auto_recruit=True`,
     `initial_recruitment_size=12`.
   - `audio_gibbs/experiment.py`: recruiter `hotair` (safe local default).
   - `audio_gibbs/experiment.py.prolific`: `auto_recruit=True`,
     `initial_recruitment_size=3`, `target_n_participants=5`.
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

5. Match Dallinger to the PsyNet base. For a release-tag deployment, check out
   the Dallinger version that the PsyNet tag pins in its `pyproject.toml`
   (e.g. the `vX.Y.Z` Dallinger tag satisfying the pin). For a master-based
   deployment, use the latest Dallinger `master`:

```bash
cd <dallinger-root>
git fetch origin master --tags
# Release-tag deployment:
git checkout <dallinger-tag-matching-psynet-pin>
# Master-based deployment:
# git switch master && git pull --ff-only origin master
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
   materialize scaffold templates (Dockerfile, `docker/` helpers, `pytest.ini`,
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

   - **Master-based deployment**: pin both to the latest pushed `master`
     commit hash. Never pin to a branch name; PsyNet's deploy pre-check
     rejects branch-name requirements as ambiguous.

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
   (`payment_flows_prolific/experiment.py.prolific` sets it to `False`
   explicitly;
   `audio_gibbs` relies on the `False` default). Prolific no longer supports
   the older custom-screening study creation flow; a launch payload with
   `"is_custom_screening": true` fails with Prolific error `140003`.

Deploy all three apps **in parallel**, each from its own directory with its
own app name: `payment_flows_prolific` from the main checkout (after its
Prolific-variant swap is committed on the deployment branch), and the two
paid `audio_gibbs` variants from temporary worktrees (both swaps prepared
as described in "Prepare The Recruiter Variants" below). Start each deploy
as a background process (or in separate terminals) and monitor all launch
outputs:

```bash
source <psynet-root>/<venv>/bin/activate

(cd <psynet-root>/tests/deployment/payment_flows_prolific && psynet deploy ssh \
  --server <ssh-host> \
  --dns-host <dns-host> \
  --app <payment-flows-prolific-app-name>) &

(cd <prolific-worktree>/tests/deployment/audio_gibbs && psynet deploy ssh \
  --server <ssh-host> \
  --dns-host <dns-host> \
  --app <audio-gibbs-prolific-app-name>) &

(cd <lucid-worktree>/tests/deployment/audio_gibbs && psynet deploy ssh \
  --server <ssh-host> \
  --dns-host <dns-host> \
  --app <audio-gibbs-lucid-app-name>) &

wait
```

Do not let one deployment's failure silently abort the others: check each
launch output separately, and report per-app success/failure.

Name each app after the deployment branch, experiment, and recruiter:
`test-<base-tag>-payment-flows-prolific` and
`test-<base-tag>-audio-gibbs-prolific`, appending `-2`, `-3`, ... for repeat
deployments. App names only allow `a-z`, `0-9`, and `-` (the deploy command
rejects anything else), so replace the dots in the base tag with dashes,
e.g. base tag `v13.3.0rc1` gives `test-v13-3-0rc1-payment-flows-prolific-1`
and `test-v13-3-0rc1-audio-gibbs-prolific-1`. For a master-based
deployment the same rule applied to the branch name gives e.g.
`test-master-8ece25f0-payment-flows-prolific-1`. Because the
per-deployment folder under `deployment-tests/` is named after the app,
this also keeps master-based audit folders clearly separate from
release-tag ones. (Older deployments used the app names
`test-<base-tag>-prolific` and `test-<base-tag>-audio-gibbs`, before the
recruiter suffix became part of the convention.) After deployment, inspect
each launch output for the experiment URL, dashboard URL, and Dozzle URL.

