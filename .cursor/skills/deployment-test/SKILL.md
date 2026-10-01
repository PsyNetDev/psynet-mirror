---
name: deployment-test
description: Debug deployed PsyNet test experiments via dashboard and Dozzle logs, infer app names from URLs, and summarize deployment/recruiter errors. Use when debugging a deployed PsyNet experiment, running RC validation deploys, or inspecting test deployment apps. After a test app is deployed, keep monitoring it until that recruiter run finishes.
compatibility: Requires SSH access to the deployment server. Recruiter and dashboard credentials are in ~/.dallingerconfig; Dozzle credentials are in deploy output. Never commit them.
---

# Deployment test

Workflow for deployed PsyNet test experiments. After launch, watch every
app until its recruiter run finishes. Also use it when the user provides
URLs, app names, or asks to inspect a dashboard or logs.

## Prerequisites

- Confirm `<psynet-root>`, `<dallinger-root>`, `<venv>`, SSH host/key, and DNS host with the user.
- Activate `<psynet-root>/<venv>` before any PsyNet/Python command.
- Load dashboard, Dozzle, and recruiter credentials from the local sources in
  `references/browser-and-dashboard.md`. Do not ask the user to paste them
  unless those sources are missing or login fails. Never record them in
  committed files or print the values.

See `references/browser-and-dashboard.md` for default URLs and credential lookup.

## Workflow

1. **Deploy** (optional full test): follow `references/deploy-from-test-branch.md`.
   Prepare paid variants per `references/recruiter-variants.md`. Prolific
   swaps `config.txt` only; Lucid `audio_gibbs` also copies
   `experiment.py.lucid`. Diff-check before deploy and inspect the running
   container after launch — do not trust the git branch alone. Stagger
   local prepare, then overlap remote builds — do not start all
   `psynet deploy ssh` commands at once. Name branches and apps with the
   PsyNet version from `pyproject.toml` (including alpha, e.g.
   `v13.4.0a0`), then the commit hash when the base is not that tag (see
   naming in `deploy-from-test-branch.md`).
2. **Infer app name** from the experiment URL hostname (first segment).
3. **Inspect** dashboard and Dozzle per `references/browser-and-dashboard.md`.
4. **Monitor until finished.** This starts at launch and is not optional.
   Follow [Monitor until finished](#monitor-until-finished).
5. **Download logs** with `references/dozzle-log-download.md`; review using
   `references/log-review-checklist.md`.
6. **Report** per `references/reporting.md`. Archive audit folders in the private
   `psynet-deployment-tests` repository — never commit under `deployment-tests/` in PsyNet.

RC deployments: end each app's `analysis.md` with an explicit promotion verdict
(recommend final release vs another RC).

## Monitor until finished

Watch every deployed test app until its recruiter run is finished, or until
the user says to stop. A successful launch is not the end of the task, and
a later turn that finds a live test app with no watch running starts one
without being asked.

Use the poll and chat cadence in
`references/observe-prolific-completion.md` (Regular polls and chat news).
Lucid apps use that same cadence with the notes in
`references/recruiter-variants.md`. One combined status covers every app
still in flight; do not drop an app because another has not moved.

Keep the watch alive across turns with one local wake loop for the whole
set (Cursor loop skill, monitored shell output). Poll on each tick, append
the snapshot to `/tmp/<base-name>-observe.jsonl`, and post only on the
cadence above. Example sentinel:

```bash
while true; do
  sleep 180
  echo 'AGENT_LOOP_TICK_deploy_watch {"prompt":"Poll every live deployment-test app. Append a snapshot to /tmp/<base-name>-observe.jsonl. Post a short status if something changed or 10 minutes have passed."}'
done
```

Stop that loop only when every watched app is terminal — Prolific
`study_status == COMPLETED`, or the Lucid survey has reached its target
or been stopped — or the user asks to stop. Then continue with log
download and `analysis.md` for each finished app.

Related: `release/references/release-candidates.md` (RC validation gate).
