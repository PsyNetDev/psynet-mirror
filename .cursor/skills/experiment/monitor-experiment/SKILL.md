---
name: monitor-experiment
description: Monitor active or recently deployed PsyNet experiments for participant flow, data integrity, deployment health, export readiness, and safe handoff decisions.
---

# PsyNet experiment monitoring

## Prerequisites

- Read `deploy-experiment/SKILL.md` before recommending export, destroy, or
  teardown commands.
- Read `record-participant-video/SKILL.md` when monitoring depends on
  participant-facing evidence, audio playback, timing-sensitive UI, or live
  human review.
- Read `participant-quality-telemetry/SKILL.md` when monitoring
  attention, paste behavior, AI-assistance disclosures, or quality flags.
- Read `simulate-participants/SKILL.md` when comparing live behavior
  against simulated profiles or using bots as a dry-run baseline.
- Read `filter-participants/SKILL.md` when failures involve
  prescreening, recruiter routing, failed participants, or platform
  qualifications.

## Monitoring scope

Before taking action, record:

- experiment folder and branch;
- app name and server name if deployed;
- dashboard or preview URL;
- recruiter and recruitment state;
- expected participant count or stopping rule;
- expected trial/module count per participant;
- active credentials or access blockers;
- whether the task is local preview, live human review, pilot, production, or
  post-run export.

Do not invent credentials or access. If dashboard, SSH, database, AWS, or
recruiter access is unavailable, write the specific blocker and continue with
local or exported evidence only.

When a reviewable static dashboard snapshot is needed for an experiment audit,
save authenticated dashboard HTML to `audit/artifacts/monitor.html` and follow
`produce-experiment-audit/references/populating-an-audit.md` (Monitor snapshot).
Do not confuse that file with live monitoring of an ongoing recruitment.

## Health checks

Check participant flow:

- consent/ad page loads;
- instructions and prescreeners are reachable;
- media assets load and play;
- recording, microphone, or browser permissions work when required;
- representative trials can be completed;
- failed prescreeners exit cleanly and do not consume main-task quota;
- completion redirects to the expected recruiter or end page.

Check operational health:

- app/server names match logs and deployment records;
- no obvious error loop in logs;
- participant counts move as expected;
- trial, module, and network tables grow coherently;
- assets are not missing from the deployed environment;
- resource usage or queue behavior is not obviously stalled;
- no known paid resources are left running beyond the approved scope.

Check data integrity:

- participant rows, trial rows, module states, assets, and questionnaire answers
  are present for at least one completed run;
- required metadata fields are populated and typed consistently;
- condition assignment and grouping look plausible;
- quality or telemetry flags are reviewable rather than silently excluding data;
- export paths and file names are recorded with timestamps.

## Stop, continue, or fix

Use conservative decision labels:

- continue: flow, logs, counts, and data integrity match expectations;
- continue-with-watch: minor issue is documented and not scientifically
  threatening;
- pause: participant experience, payment path, data loss risk, or validity is
  uncertain;
- stop-and-fix: severe bug, broken recruiter path, missing required data, unsafe
  credential exposure, or paid-resource risk;
- export-and-handoff: run is complete or should be frozen before further changes.

Do not destroy apps, tear down servers, stop recruitment, or change live
recruiter settings unless the user explicitly asks for that operation.

## Evidence and handoff

Create or update a monitoring note such as `MONITORING_LOG.md` or
`DEPLOYMENT_LOG.md` with:

- timestamp and operator;
- scope and access available;
- commands or pages inspected;
- participant-flow evidence links or screenshots;
- health-check summary;
- data-integrity summary;
- export status and path, or blocker;
- decision label;
- unresolved risks and next action.

For live human review before deployment, provide a preview URL or tunnel only
when the environment already supports it and the user has approved sharing. Make
the review task narrow: what the human should test, what screenshots or notes to
collect, and which issues should block deployment.
