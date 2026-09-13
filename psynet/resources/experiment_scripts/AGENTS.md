# Agent instructions

On Windows, develop in WSL (Ubuntu) using Linux commands. Native Windows is not supported.

PsyNet is a framework for designing and deploying online psychological experiments.
The agent is there to help both with the development of the PsyNet source code,
and with the development of individual PsyNet experiments.

If the root contains a file called `experiment.py`, assume that we are working on an experiment.
Otherwise assume we are working on the PsyNet source code.

From `experiment.py`, import sibling modules with `from . import my_module`.
Do not run `python experiment.py` to validate imports; use `psynet test local`.
See `docs/experiment_development/experiment_directory.rst`
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

- Install Python 3.13 (use same version specified in `Dockerfile`)
- Install uv (`pip3 install uv`)

## Before running commands

### System dependencies

Cloud agents will need to install the following dependencies.
Local agents should check for their availability and install if necessary.

- **Python 3.13.x**: Install a 3.13 release and verify `python3 --version`.
  Check the repository Dockerfile for the exact patch version we target
  (e.g., `psynet/resources/experiment_scripts/Dockerfile` or the root `Dockerfile`).
- **uv**: Install via `pip`.
- **PostgreSQL**: Install the server and client, ensure the service is running,
  and create the `dallinger` user/database if they do not exist. When prompted by
  `createuser -P`, set the password to `dallinger` (per the installation docs).
  Verify with `psql -h localhost -U dallinger -d dallinger`.
- **Redis**: Install the Redis server, ensure it is running, and verify with
  `redis-cli ping` (expect `PONG`).
- **Heroku CLI**: Install the CLI so `heroku` commands are available and verify
  with `heroku --version`.
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

Demos are contained in `demos/experiments` and `demos/features`.
If a user asks for the X demo, list all child directories in `demos/experiments` and `demos/features` to see which they mean.

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
- `response` - Participant responses/answers
- `node` - Network nodes
- `network` - Experiment networks
- `info` - Information objects
- `experiment` - Experiment metadata
- `experiment_status` - Current experiment status

Example queries:

```sql
-- List recent participants
SELECT id, worker_id, status, creation_time FROM participant ORDER BY creation_time DESC LIMIT 5;

-- View participant responses
SELECT id, answer FROM response ORDER BY id DESC LIMIT 10;

-- List all tables
\dt
```

## Further information

If in the PsyNet repository, find further documentation in `docs`.
If in an experiment directory, find more information at https://psynetdev.gitlab.io/PsyNet/.

For PsyNet 14 migrations (in-place timeline defaults, fragment templates,
managed page JavaScript, `psynet.var`, JsPsych module timelines), follow
https://psynetdev.gitlab.io/PsyNet/whats_new/upgrading_to_psynet_14.html
(pip installs do not ship the `docs/` RST tree). In a PsyNet source checkout
you may read `docs/whats_new/upgrading_to_psynet_14.rst` instead. In Cursor,
run `/upgrade-to-psynet-14` to follow that checklist.
