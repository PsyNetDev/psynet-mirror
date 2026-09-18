# Prepare recruiter variants


Both experiments' default `experiment.py` files use HotAir so running a
directory directly cannot accidentally start paid recruitment. Before
starting the three parallel deploy commands above, swap in the paid
variants.

1. `payment_flows_prolific` has a single paid variant, so swap it directly
   on the deployment branch and commit (this is the state the main-checkout
   deploy uses):

```bash
cd <psynet-root>/tests/deployment/payment_flows_prolific
cp experiment.py.prolific experiment.py
cp config.txt.prolific config.txt
# config.txt is gitignored under tests/deployment/.
git add experiment.py && git add -f config.txt
git commit -m "Switch payment_flows_prolific to Prolific variant for deployment"
git push
```

2. `audio_gibbs` has two paid variants sharing one directory, so prepare
   them in separate temporary worktrees on branches off the deployment
   branch; each worktree branch records exactly what was deployed:

```bash
cd <psynet-root>
git worktree add -b deployment-tests/<base-tag>-audio-gibbs-prolific \
  /tmp/psynet-audio-gibbs-prolific-deploy deployment-tests/<base-tag>
cd /tmp/psynet-audio-gibbs-prolific-deploy/tests/deployment/audio_gibbs
cp experiment.py.prolific experiment.py
cp config.txt.prolific config.txt
# config.txt is gitignored under tests/deployment/.
git add experiment.py && git add -f config.txt
git commit -m "Switch audio_gibbs to Prolific variant for deployment"
git push -u origin deployment-tests/<base-tag>-audio-gibbs-prolific

cd <psynet-root>
git worktree add -b deployment-tests/<base-tag>-audio-gibbs-lucid \
  /tmp/psynet-audio-gibbs-lucid-deploy deployment-tests/<base-tag>
cd /tmp/psynet-audio-gibbs-lucid-deploy/tests/deployment/audio_gibbs
cp experiment.py.lucid experiment.py
cp config.txt.lucid config.txt
git add experiment.py && git add -f config.txt
git commit -m "Switch audio_gibbs to Lucid variant for Lucid deployment"
git push -u origin deployment-tests/<base-tag>-audio-gibbs-lucid
```

3. Deploy from the worktrees (these are the second and third parallel
   `psynet deploy ssh` commands shown above). Name the Lucid app
   `test-<base-tag>-audio-gibbs-lucid`, appending `-2`, `-3`, ... for repeat
   deployments (e.g. `test-v13-3-0rc1-audio-gibbs-lucid-1`).

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
  Lucid recruiter-state evidence instead).

