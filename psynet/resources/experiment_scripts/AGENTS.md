# Agent instructions

On Windows, develop in WSL (Ubuntu) using Linux commands. Native Windows is not supported.

PsyNet is a framework for designing and deploying online psychological experiments.
If the root contains a file called `experiment.py`, assume that we are working on an experiment.
Otherwise assume we are working on the PsyNet source code.

To implement an experiment from a description, follow the `implement-experiment`
skill before writing code: `.cursor/skills/psynet/implement-experiment/SKILL.md`
in an experiment directory, or `.cursor/skills/experiment/implement-experiment/SKILL.md`
in the PsyNet source code. It says when to use the other experiment skills.

`psynet scripts update` installs the PsyNet skills under `.cursor/skills/psynet/`.
Don't edit them there; that directory is gitignored and overwritten on update.
Skills elsewhere under `.cursor/skills/` belong to the experiment.

## Setup

Follow the `install` page (see "Documentation" below). In short: use a
virtual environment at `.venv/` (ask the user before creating one with
`uv venv --python 3.13`, which downloads Python if it is missing), then run
`uv pip install psynet` and `psynet setup`, which installs the experiment
dependencies. Start PostgreSQL and Redis with `psynet services ensure`.
Without Docker (for example on some cloud agents), install both natively and
create a `dallinger` PostgreSQL user and database with password `dallinger`.

In Cursor, disable sandboxing when running PsyNet commands by setting
`required_permissions: ["all"]`.

## Running experiments locally

`psynet test local` runs in its own database, Redis server and port, so it
can run while another experiment is being served or tested. `psynet debug
local` sessions, however, share port 5000, the PostgreSQL database, Redis and
Dallinger's development folder, and starting one stops the other's worker
processes. Before `psynet debug local`, check that nothing is listening on
port 5000 (`lsof -nP -iTCP:5000 -sTCP:LISTEN`). If
another experiment is running, don't stop it yourself: either ask the user to
stop it, or run yours alongside it with its own database, Redis server and
port, as described in "Run several experiments at once" in
`code/project/running_and_debugging`.
`psynet deploy` also clears the local database and Redis, so don't run it
while a local experiment is running.

From `experiment.py`, import sibling modules with `from . import my_module`.
Validate code with `psynet test local`, not `python experiment.py`. For
running, debugging and inspecting the database, read
`code/project/running_and_debugging`. After `psynet debug local`, the log
prints an ad page URL such as
`http://127.0.0.1:5000/ad?generate_tokens=true&recruiter=hotair`; offer to
walk through the experiment in the browser. When you start the server from a
non-interactive background shell, keep stdin open
(`tail -f /dev/null | psynet debug local`); otherwise it can stop without a
log line.

The `demos/index` page describes each PsyNet demo. `psynet docs demos` prints
the folder holding their code for the installed version (without media).

## Documentation

The PsyNet documentation is the source of truth for how PsyNet works. Read the
relevant page before writing or changing experiment code, rather than relying on
memory. Use the local copy that matches the installed PsyNet version:

- Run `psynet docs path` once per session and reuse the printed folder.
- `rg -n -i --no-ignore "<term>" <folder>` searches every page at once.
  Keep `--no-ignore`: release installs keep the pages inside the Git-ignored
  `.venv`, which `rg` otherwise skips. In a PsyNet source checkout, also pass
  `-g '!_build'` so that matches in the built HTML don't drown out the pages.
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
| Deploying, `deploy.toml` and running a study | `deploy/how_deployment_works`, `deploy/setting_up_a_server`, `deploy/running_a_study`, `deploy/recruiters/index` |
| Exporting, basic data and analysis | `data/exporting_data`, `data/basic_data`, `data/analyzing_data` |
| Demos to start from | `demos/index` |
| Configuration and commands | `reference/configuration`, `reference/command_line` |
| Classes and functions (API) | `reference/api/index` |
| Local problems | `troubleshooting`, `wsl_troubleshooting` |

For PsyNet 14 migrations (in-place timeline defaults, fragment templates,
managed page JavaScript, `psynet.var`, JsPsych module timelines), follow
`whats_new/upgrading_to_psynet_14`. In Cursor, run `/upgrade-to-psynet-14` to
follow that checklist.
