# Agent instructions

On Windows, develop in WSL (Ubuntu) using Linux commands. Native Windows is not supported.

PsyNet is a framework for designing and deploying online psychological experiments.
The agent is there to help both with the development of the PsyNet source code,
and with the development of individual PsyNet experiments.

If the root contains a file called `experiment.py`, assume that we are working on an experiment.
Otherwise assume we are working on the PsyNet source code.

To implement an experiment from a description, follow the `implement-experiment`
skill before writing code: `.cursor/skills/psynet/implement-experiment/SKILL.md`
in an experiment directory, or `.cursor/skills/experiment/implement-experiment/SKILL.md`
in the PsyNet source code. It says when to use the other experiment skills.

From `experiment.py`, import sibling modules with `from . import my_module`.
Do not run `python experiment.py` to validate imports; use `psynet test local`.
See `docs/code/project/experiment_directory.rst`
("Importing other Python files").

PsyNet experiment skills are installed under `.cursor/skills/psynet/` by
`psynet scripts update` (and created when missing by `psynet scripts scaffold`).
Treat that directory as PsyNet-managed: update the canonical skills in the
PsyNet source repository rather than editing generated copies in an experiment.
It is gitignored in experiment repositories. Skills elsewhere under
`.cursor/skills/` belong to the experiment and are preserved by
`psynet scripts update`.

## Agent Skills authoring

The canonical skill format spec is `.cursor/skills/create-skill/SKILL.md` in the
PsyNet source repository. Experiment skills live under
`.cursor/skills/experiment/`; repo meta skills live under `.cursor/skills/`.
After editing skills, run `python scripts/validate_agent_skills.py` and refresh
experiment copies with `psynet scripts update`. Then reread the result using
the "After writing" section of that skill.

The PsyNetSkills workshop repository adds a thin `create-skill` addendum for
challenge/attempt workflows and `psynetsk-validate`.

## Initial setup

- Install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`); uv installs
  Python 3.13, the version in the `Dockerfile`.
- Follow the Install page for the other tools (see "Documentation" below).

## Before running commands

### System dependencies

Cloud agents will need to install the following dependencies.
Local agents should check for their availability and install if necessary.

- **Python 3.13.x**: Install a 3.13 release and verify `python3 --version`.
  Check the repository Dockerfile for the exact patch version we target
  (e.g., `psynet/resources/experiment_scripts/Dockerfile` or the root `Dockerfile`).
- **uv**: Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **PostgreSQL and Redis**: Where Docker is available, run
  `psynet services ensure`, which starts both in Docker containers, and check
  them with `psynet services check`. Without Docker (for example on some cloud
  agents), install the servers natively: ensure both services are running,
  create the `dallinger` PostgreSQL user and database with password
  `dallinger`, and verify with `psql -h localhost -U dallinger -d dallinger`
  and `redis-cli ping` (expect `PONG`).
- **Heroku CLI**: Install the CLI and verify with `heroku --version`.
  `psynet test local` uses its `heroku local` process manager; no Heroku
  account is needed.
- **Chromedriver**: Leave uninstalled by default; only install it if you need
  browser automation.

### Python dependencies

By default, assume a Python virtual environment located at `.venv/`.
Activate it before running Python commands.
Cloud agents should create this environment automatically via `uv`.
Local agents should prompt the user before doing so.

Install dependencies as follows:

- (For PsyNet source checkout): `uv pip install -e '.[dev,demos,slack]'`
- (For standalone experiments): `uv pip install psynet` (bootstrap only), followed by
  `psynet setup` to scaffold and install `psynet[experiment]` via the generated
  `constraints.txt`.

If dependency installation fails with `pg_config executable not found`, install
PostgreSQL development headers (e.g. `libpq-dev` on Debian/Ubuntu,
`postgresql-devel` on Fedora, `brew install postgresql` on macOS) and retry.

Cursor: disable sandboxing when running PsyNet commands by setting `required_permissions: ["all"]`.

## Demos

Demos are contained in `demos/experiments`, `demos/features` and `demos/pipelines`
of the PsyNet source code; pip installs do not include them. Outside a source checkout,
the `demos/index` documentation page describes every demo and links to its code.
If a user asks for the X demo, list all child directories of those three folders to see which they mean.

## Running experiments locally

The PsyNet demo directories include just the authored experiment files.
Their unpinned `requirements.txt` files and omitted constraints are intentional.
Within the PsyNet source checkout, PsyNet automatically generates ignored
boilerplate when a bundled demo is run or tested:

```bash
psynet debug local
```

Pytest scaffolds demos temporarily via the `in_experiment_directory` fixture.
On teardown it removes only paths that were absent when the fixture started,
so pre-existing scaffold leftovers and customized files remain untouched.

For a copied standalone demo, create its complete environment:

```bash
uv venv --python 3.13
source .venv/bin/activate
uv pip install psynet      # bootstrap only (no experiment runtime yet)
psynet setup               # scaffolds files, initializes Git, installs psynet[experiment]
```

To run an experiment in debug mode:

```bash
cd demos/.../<experiment_name>
psynet debug local
```

For example, to run the timeline demo:

```bash
cd demos/experiments/timeline
psynet debug local
```

Wait for 8 seconds for the server to start.

Inspect the logs to see relevant URLs.
Look out for an ad page URL, something like
http://127.0.0.1:5000/ad?generate_tokens=true&recruiter=hotair.

When the demo is running, offer the user to navigate the experiment automatically.

## Deployment files

`deploy.toml` uses an `[exclude]` table: `paths` (root-relative prefixes),
`names` (basenames in every directory), and `suffixes` (literal endings
such as `.db`). PsyNet creates it from the template when missing and never
overwrites a custom copy. Inspect the current plan with
`dallinger deployment-files list`. Stock excludes include the local
`audit/` review packet (not needed at runtime). PsyNet never overwrites a
custom `deploy.toml`; add `audit` to `[exclude].paths` on existing
experiments that still ship that directory.

Pregenerated public stimuli belong in `static/` (served as `/static/...`).
They are included in the deployment plan. Generated `static/assets` is
excluded. The default package-size limit is 1024 MB; raise `EXP_MAX_SIZE_MB`
only after reviewing the file list.
Use PsyNet assets for recordings and other files created during the experiment.

`.dockerignore` is no longer supported. Move any custom exclusions into
`deploy.toml` and remove `.dockerignore` before debug or deployment.

## Navigating experiments

Cursor's browser extension can be used to interact with experiments programmatically:

1. Navigate to the ad page URL
2. Click "Begin Experiment"
3. Progress through consent and experiment pages
4. Form inputs can be filled and buttons clicked automatically

This is useful for automated testing of experiment flows.

## Database access

PsyNet uses PostgreSQL. Connect using:

```bash
psql -h localhost -U dallinger -d dallinger
```

Cursor: this needs `required_permissions: ["network"]`.

Key tables:

- `participant` - Experiment participants (id, worker_id, status, creation_time)
- `trial` - Trials, with their definitions and answers
- `response` - Page responses/answers
- `node` - Trial maker nodes
- `network` - Trial maker networks (chains)
- `asset` - Stored files and their metadata

Example queries:

```sql
-- List recent participants
SELECT id, worker_id, status, creation_time FROM participant ORDER BY creation_time DESC LIMIT 5;

-- View participant responses
SELECT id, answer FROM response ORDER BY id DESC LIMIT 10;

-- List all tables
\dt
```

## Documentation

The PsyNet documentation is the source of truth for how PsyNet works. Read the
relevant page before writing or changing experiment code, rather than relying on
memory. Use the local copy that matches the installed PsyNet version:

- Run `psynet docs path` once per session and reuse the printed folder.
- `rg -n -i --no-ignore "<term>" <folder>` searches every page at once.
  Keep `--no-ignore`: release installs keep the pages inside the Git-ignored
  `.venv`, which `rg` otherwise skips.
- Read a page from the table below at `<folder>/<page>` plus `.txt` (release
  installs) or `.rst` (source checkouts), or with `psynet docs show <page>`.

Release installs ship the pages as plain text, including the API reference.
In a PsyNet source checkout the folder is `docs/`, whose RST sources only
reference the API; search `psynet/` for docstrings there. If `psynet docs path` reports that
there is no local copy (for example in a Git install), it prints the matching
version of the documentation website; fetch `<that URL><page>.html`.

| Topic | Page |
| --- | --- |
| Installing tools, local services | `install` |
| First experiment with a coding agent | `quickstart`, `code/project/agentic_programming` |
| Recommended workflows (Agent Skills) | `skills/index` |
| Design concepts (timeline, pages, trials, chains, stimuli, participants, groups) | `design/timeline`, `design/pages`, `design/trials`, `design/chains`, `design/stimuli`, `design/participants`, `design/groups` |
| Experiment files and dependencies | `code/project/experiment_directory`, `code/project/dependencies` |
| Running and debugging locally | `code/project/running_and_debugging` |
| Timelines, code blocks, loops, variables | `code/writing_a_timeline` |
| Pages, prompts, controls, validation | `code/writing_pages`, `code/pages/control_gallery` |
| Custom front ends and graphics | `code/pages/custom_front_ends`, `code/pages/graphics` |
| Static trial makers, scoring, performance checks | `code/writing_a_trial_maker` |
| Chains (iterated, Gibbs, MCMCP, create and rate) | `code/writing_a_chain_experiment` |
| Adaptive experiments | `code/writing_a_trial_maker`, `code/writing_a_chain_experiment`; workflow in the `make-experiment-adaptive` skill |
| Stimuli, `static/`, assets | `code/using_stimuli`, `code/trials/assets` |
| Payment and bonuses | `code/participants/payment` |
| Pre-screening and questionnaires | `code/participants/prescreening_and_questionnaires` |
| Translation | `code/participants/internationalization` |
| Groups, barriers, chatrooms, real-time interaction | `code/multiplayer/synchronization`, `code/multiplayer/realtime_interaction` |
| Bots and automated tests | `test/backend` |
| Browser layout checks | `test/frontend` |
| Performance tests | `test/scalability` |
| Audits | `test/audits`, `test/audit_reference` |
| Design simulation and power analysis | `test/audit_reference`; workflow in the `power-analysis` skill |
| Deploying and running a study | `deploy/how_deployment_works`, `deploy/setting_up_a_server`, `deploy/running_a_study`, `deploy/recruiters/index` |
| Exporting, basic data and analysis | `data/exporting_data`, `data/basic_data`, `data/analyzing_data` |
| Demos to start from | `demos/index` |
| Configuration and commands | `reference/configuration`, `reference/command_line` |
| Classes and functions (API) | `reference/api/index` |
| Local problems | `troubleshooting`, `wsl_troubleshooting` |

For PsyNet 14 migrations (in-place timeline defaults, fragment templates,
managed page JavaScript, `psynet.var`, JsPsych module timelines), follow
`whats_new/upgrading_to_psynet_14`. In Cursor, run `/upgrade-to-psynet-14` to
follow that checklist.
