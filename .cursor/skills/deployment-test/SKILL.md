---
name: deployment-test
description: Debug deployed PsyNet test experiments via dashboard and Dozzle logs, infer app names from URLs, and summarize deployment/recruiter errors. Use when debugging a deployed PsyNet experiment, running RC validation deploys, or inspecting test deployment apps.
compatibility: Requires SSH access to the deployment server. Recruiter and dashboard credentials are in ~/.dallingerconfig; Dozzle credentials are in deploy output. Never commit them.
---

# Deployment test

Workflow for deployed PsyNet test experiments when the user provides URLs,
app names, or asks to inspect dashboard/logs.

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
   Prepare paid variants per `references/recruiter-variants.md`. Copy
   `experiment.py` and `config.txt` for that recruiter, then diff-check
   before deploy and inspect the running container after launch — do not
   trust the git branch alone. Stagger local prepare, then overlap remote
   builds — do not start all `psynet deploy ssh` commands at once. Name
   branches and apps with the PsyNet version from `pyproject.toml`
   (including alpha, e.g. `v13.4.0a0`), then the commit hash when the
   base is not that tag (see naming in `deploy-from-test-branch.md`).
2. **Infer app name** from the experiment URL hostname (first segment).
3. **Inspect** dashboard and Dozzle per `references/browser-and-dashboard.md`.
4. **Observe** recruiter completion per `references/observe-prolific-completion.md`
   (Prolific apps; Lucid uses the adapted notes in recruiter-variants).
   Poll on a timer and post short chat status updates; do not wait silently
   until completion.
5. **Download logs** with `references/dozzle-log-download.md`; review using
   `references/log-review-checklist.md`.
6. **Report** per `references/reporting.md`. Archive audit folders in the private
   `psynet-deployment-tests` repository — never commit under `deployment-tests/` in PsyNet.

RC deployments: end each app's `analysis.md` with an explicit promotion verdict
(recommend final release vs another RC).

Related: `release/references/release-candidates.md` (RC validation gate).
