# Prepare recruiter variants


The experiments' defaults cannot start paid recruitment (devprolific for
`payment_flows_prolific`, HotAir for `audio_gibbs`). Before starting the
three staggered deploy commands above, swap in the paid variants.

Copy the matching `experiment.py` and `config.txt`, then **diff-check**
before deploy and **inspect the running container** after launch: a
wrong `experiment.py` still starts a paid survey.

1. `payment_flows_prolific` selects its recruiter via the config file, so
   swap in the paid config directly on the deployment branch and commit
   (this is the state the main-checkout deploy uses):

```bash
cd <psynet-root>/tests/deployment/payment_flows_prolific
cp config.txt.prolific config.txt
# config.txt is gitignored under tests/deployment/.
git add -f config.txt
git commit -m "Switch payment_flows_prolific to Prolific recruiter for deployment"
git push
```

2. `audio_gibbs` has two paid variants sharing one directory, so prepare
   them in separate temporary worktrees on branches off the deployment
   branch; each worktree branch records exactly what was deployed.

```bash
cd <psynet-root>
git worktree add -b deployment-tests/<base-name>-audio-gibbs-prolific \
  /tmp/psynet-audio-gibbs-prolific-deploy deployment-tests/<base-name>
cd /tmp/psynet-audio-gibbs-prolific-deploy/tests/deployment/audio_gibbs
cp experiment.py.prolific experiment.py
cp config.txt.prolific config.txt
# config.txt is gitignored under tests/deployment/.
diff -q experiment.py experiment.py.prolific
git add experiment.py && git add -f config.txt
git commit -m "Switch audio_gibbs to Prolific variant for deployment"
git push -u origin deployment-tests/<base-name>-audio-gibbs-prolific

cd <psynet-root>
git worktree add -b deployment-tests/<base-name>-audio-gibbs-lucid \
  /tmp/psynet-audio-gibbs-lucid-deploy deployment-tests/<base-name>
cd /tmp/psynet-audio-gibbs-lucid-deploy/tests/deployment/audio_gibbs
cp experiment.py.lucid experiment.py
cp config.txt.lucid config.txt
diff -q experiment.py experiment.py.lucid
test -n "$(rg -n '_stop_lucid_fielding' experiment.py)"
git add experiment.py && git add -f config.txt
git commit -m "Switch audio_gibbs to Lucid variant for Lucid deployment"
git push -u origin deployment-tests/<base-name>-audio-gibbs-lucid
```

   Do not start `psynet deploy ssh` for a variant until those `diff` /
   `rg` checks pass. After each app launches, confirm the **running**
   container (not only the git branch) has the right code:

```bash
ssh -i <ssh-key> <ssh-user>@<ssh-host> \
  "docker compose -f ~/dallinger/<app-name>/docker-compose.yml exec -T web python - <<'PY'
import inspect
from dallinger.config import get_config
from dallinger_experiment.experiment import Exp
print('recruiter', get_config().get('recruiter'))
print('has_stop_lucid', '_stop_lucid_fielding' in inspect.getsource(Exp))
PY"
```

   Lucid app must print `recruiter lucid-recruiter` and `has_stop_lucid True`.
   Prolific app must print `recruiter prolific` and `has_stop_lucid False`.
   Each paid variant also aborts in `on_launch` (before recruitment
   opens) unless the configured recruiter matches that file: Lucid
   requires `lucid-recruiter`, Prolific requires `prolific` or
   `devprolific`.
   If either check fails, close any live Lucid survey immediately, destroy
   the app, and redeploy from a worktree that passed the file diffs. Do
   not keep watching a mismatched app.

3. Deploy from the worktrees (these are the second and third staggered
   `psynet deploy ssh` commands shown above). Name the Lucid app
   `test-<base-name>-audio-gibbs-lucid`, appending `-2`, `-3`, ... for repeat
   deployments (e.g. `test-v13-3-0rc1-audio-gibbs-lucid-1`, or
   `test-v13-4-0a0-7e0c52c31-audio-gibbs-lucid-1` when the base is an
   unreleased alpha commit).

4. After both deploys have launched, remove the worktrees (the pushed
   branches preserve the deployed code for auditing):

```bash
cd <psynet-root>
git worktree remove /tmp/psynet-audio-gibbs-prolific-deploy
git worktree remove /tmp/psynet-audio-gibbs-lucid-deploy
```

Notes for the Lucid app:

- Like the Prolific configs, `config.txt.lucid` sets
  `publish_experiment = true`, so the Lucid survey goes live automatically at
  launch (survey status `03`) instead of requiring manual publication in the
  Lucid marketplace.
- The "Observe Until Prolific Completion" workflow below is
  Prolific-specific. For the Lucid app there is no Prolific study to poll;
  observe the dashboard participant table, recruiter state, and Dozzle logs
  until the target number of participants completes or the user stops the
  test, then apply the same per-app audit-trail workflow (skipping the
  Prolific study/submissions JSON artifact and capturing the equivalent
  Lucid recruiter-state evidence instead). Use the same 3-minute poll /
  10-minute chat-news cadence as the Prolific observe notes.
