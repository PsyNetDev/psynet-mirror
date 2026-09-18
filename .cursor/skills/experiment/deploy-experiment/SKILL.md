---
name: deploy-experiment
description: Audit PsyNet experiment folders for deployment readiness, deployment records, export safety, app/server naming, EC2 teardown, and common local or SSH deployment blockers. Use when preparing PsyNet deployments, reconstructing deployment state, generating safe commands, or diagnosing deployment failures.
---

# PsyNet Deployment Ops

## Safety rules

- Do not run paid recruitment, app destruction, EC2 teardown, or other
  irreversible commands unless the user explicitly asks.
- Before any destroy/teardown recommendation, verify whether data has been
  exported and record the export path or blocker.
- Do not commit or publish real AWS credentials, recruiter tokens, dashboard
  passwords, `.env` files, private keys, or participant data.
- Prefer command generation and readiness reports over live operations unless
  the task explicitly asks for execution.

## Readiness audit

Check that the experiment folder has:

- `experiment.py`
- `config.txt`
- `requirements.txt`
- `constraints.txt`
- `Dockerfile` and/or `Dockertag` when the template expects them
- `.gitignore` excluding `.venv/`, `.deploy/`, `.pytest_cache/`, `exports/`,
  `deploy_logs/`, source archives, generated logs, and the managed
  `.cursor/skills/psynet/` bundle
- recruiter/qualification JSON files when a recruiter requires them
- qualification files and recruiter settings that match any in-experiment
  prescreeners; use `filter-participants/SKILL.md` when the
  mapping is unclear
- local assets or manifests present and deployable
- no broken symlinks to local user paths
- no stale app/server/study names copied from another template
- a `DEPLOYMENT_LOG.md` or clear deployment metadata

## Dependency checks

- Install from `constraints.txt`, not directly from `requirements.txt`.
- Prefer `psynet setup` to regenerate constraints and refresh the environment
  when dependencies intentionally change or `constraints.txt` is missing.
- If local and deployed behavior differ, check for stale constraints, Docker
  context problems, missing assets, and hardcoded local paths.

## Deployment records

`DEPLOYMENT_LOG.md` is not a core PsyNet file. It is an emerging lab
practice for making deployments recoverable by humans and agents. If a folder
uses another deployment record, inspect that instead. If no record exists,
recommend creating one.

A useful deployment record should include:

- folder path
- app name
- server name
- DNS host
- region
- instance type
- recruiter
- qualification/config files
- provision command
- deploy command
- dashboard/log URLs
- export command and path
- destroy app command
- EC2 teardown command
- final verification command

## Command patterns

Local debug:

```bash
source .venv/bin/activate
psynet debug local
```

Provision:

```bash
dallinger ec2 provision \
  --name <server-name> \
  --region <region> \
  --dns-host <server-name>.cap-experiments.com \
  --type m7i.xlarge
```

Deploy:

```bash
psynet deploy ssh \
  --app <app-name> \
  --dns-host <server-name>.cap-experiments.com \
  --server <server-name>.cap-experiments.com
```

Export:

```bash
psynet export ssh \
  --app <app-name> \
  --server <server-name>.cap-experiments.com \
  --path <experiment-folder>/exports
```

Destroy and teardown:

```bash
psynet destroy ssh --app <app-name> --server <server-name>.cap-experiments.com
dallinger ec2 teardown --name <server-name> --region <region> --dns-host <server-name>.cap-experiments.com
```

## Common failure modes

- `psynet debug local` fails because port 5000 is already occupied.
- `psynet debug local` package-size check counts `.venv` because the folder is
  not a git repo or ignore rules are missing.
- `dallinger ec2 list instances --all` is slow or times out; prefer explicit
  `--region` scans.
- AWS commands fail with missing credentials; do not invent credentials.
- Deployed Docker environment lacks local files, broken symlink targets, or
  external assets.
- App/server/DNS names diverge between logs, commands, and config files.
- Export exists for one app but teardown is being planned for another.
- SSL/TLS errors during first launch can be transient cold-start issues; retry
  after a short wait before changing code.
- Concurrent legacy exports can interfere with local Postgres state; prefer
  sequential exports unless the workflow has been tested.
- Relative export paths are easy to lose track of; prefer absolute `--path`
  values in export commands and logs.
- Large asset exports may fail even when anonymized tabular exports are usable;
  record exactly which export mode succeeded or failed.

