---
name: deployment-test
description: Debug deployed PsyNet test experiments via dashboard and Dozzle logs, infer app names from URLs, and summarize deployment/recruiter errors. Use when debugging a deployed PsyNet experiment, running RC validation deploys, or inspecting test deployment apps.
compatibility: Requires SSH access to the deployment server, recruiter credentials in ~/.dallingerconfig, and user-supplied dashboard/Dozzle credentials (never commit them).
---

# Deployment test

Workflow for deployed PsyNet test experiments when the user provides URLs,
app names, or asks to inspect dashboard/logs.

## Prerequisites

- Confirm `<psynet-root>`, `<dallinger-root>`, `<venv>`, SSH host/key, and DNS host with the user.
- Activate `<psynet-root>/<venv>` before any PsyNet/Python command.
- Ask the user for dashboard and Dozzle credentials; never record them in committed files.

See `references/browser-and-dashboard.md` for default URLs and credential policy.

## Workflow

1. **Deploy** (optional full test): follow `references/deploy-from-test-branch.md`.
   Prepare paid variants per `references/recruiter-variants.md` before parallel deploys.
2. **Infer app name** from the experiment URL hostname (first segment).
3. **Inspect** dashboard and Dozzle per `references/browser-and-dashboard.md`.
4. **Observe** recruiter completion per `references/observe-prolific-completion.md`
   (Prolific apps; Lucid uses the adapted notes in recruiter-variants).
5. **Download logs** with `references/dozzle-log-download.md`; review using
   `references/log-review-checklist.md`.
6. **Report** per `references/reporting.md`. Archive audit folders in the private
   `psynet-deployment-tests` repository — never commit under `deployment-tests/` in PsyNet.

RC deployments: end each app's `analysis.md` with an explicit promotion verdict
(recommend final release vs another RC).

Related: `release/references/release-candidates.md` (RC validation gate).
