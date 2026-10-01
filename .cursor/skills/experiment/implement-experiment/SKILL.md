---
name: implement-experiment
description: A structured process for implementing PsyNet experiments, including planning, simulations, analysis, and reporting. Use when implementing a PsyNet experiment from a natural-language specification.
compatibility: Requires PsyNet installed in the experiment's .venv (from PyPI via psynet setup, or optionally an editable PsyNet checkout), PostgreSQL, Redis, the Heroku CLI, and Jupyter tooling listed in requirements.txt for executed analysis notebooks.
---

# Implement PsyNet experiments

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

- `code/project/agentic_programming` — the coding-agent workflow for experiments
- `code/project/creating_an_experiment` — starting from a demo or an existing experiment
- `code/project/running_and_debugging` — running locally and inspecting the dashboard
- `test/backend` — bots and `psynet test local`

## Prerequisites

- Use the `explore-psynet-repository` skill to find the closest demo and the
  relevant documentation before starting.
- Read `references/validation.md` before finalizing functional, interactive, or
  performance checks.
- Read `simulate-participants/SKILL.md` before designing multi-profile,
  stochastic, mock-LLM, or export-validation simulations.
- Read `produce-experiment-audit/references/populating-an-audit.md` for the
  audit population contract. Standalone experiments use nested `audit/` via
  `psynet audit init` (skill `produce-experiment-audit`).

Repository-specific wrapper skills may add extra conventions around planning or
review; do not invent workshop-only layouts in this skill.

## Preview links

When a temporary public preview is needed, follow "Preview a running
experiment" in `public-tunnel/SKILL.md`.

## Steps

### Planning

The planning phase is responsible for turning the original natural-language specification into a detailed implementation plan.
The plan should be saved in `audit/PLAN.md` (required core audit section id `plan`).
Include the following sections:

#### Science (optional)

Decide whether to include this based on the prompt.
The section is most relevant if the prompt is asking specifically about
research questions, hypotheses, and the like.

#### Methods

This section should look something like methods sections in a scientific paper.
It should describe the experiment, including:

- Design: includes conditions, variables, randomizations.
- Materials: includes stimuli, questionnaires, etc.
- Procedures: includes participant workflow, trial structure, stimulus presentation, response collection.

Format in academic prose.

#### Power analysis

Follow `power-analysis/SKILL.md`. Keep sample size and other design quantities
provisional until its human-review and power-analysis workflow is complete, then
incorporate the selected design and supporting evidence into `audit/PLAN.md`
(potentially rerunning the simulations if required).

The power analysis lives in the **Power analysis** section of
`audit/simulate/design/simulation.ipynb`.

If the design is adaptive, include the selection policy in that same
simulation: compare it with a realistic non-adaptive alternative under
matched participants, items, and budgets, and check that the advantage
survives plausible misspecification. The adaptive-experiment skill describes
the procedure simulator and those comparisons; do not run a second,
unrelated Monte Carlo campaign.

#### Implementation

This section focuses on the software implementation of the experiment, including:

- What PsyNet constructs to use (trials, trial makers, modules, etc.)
- The general shape of the timeline
- The strategy for generating the stimuli
- Any external dependencies

### Human review

Once the plan is complete, ask the human user to review it and provide feedback.
Only continue when they are happy.

You may skip waiting for human confirmation when doing infrastructure testing
or dogfooding the implementation/audit workflow itself; record that assumption
briefly in `audit/PLAN.md` or `audit/TIMELINE.md` and continue.

### Developing the experiment

#### Setup

Prefer **`psynet setup`** as the general-purpose route for creating and
refreshing experiment files and the constrained environment. Do not hand-write
boilerplate (`Dockerfile`, `test.py`, `.gitignore`, `deploy.toml`, managed
skills) when setup/scaffold can produce it. Experiment-local `docker/` helper
scripts are obsolete; use `psynet debug local --docker`.

Canonical setup guidance: `code/project/agentic_programming` (see Read first)
and the experiment's `AGENTS.md`, which `psynet setup` writes.

**1. Choose a starting point**

- Start from an empty directory with a valid Python package name (not
  `code`, not names that cannot be imported), for example
  `~/psynet-experiments/<name>/`.
- Or copy the authored files of the closest PsyNet demo (or a prior
  experiment) into it. Demos ship authored files only (`experiment.py`,
  `requirements.txt`, assets); boilerplate and `constraints.txt` are
  intentionally omitted. `explore-psynet-repository` explains where to find
  demo code when PsyNet was installed with pip.

**2. Bootstrap, then run setup**

From the experiment directory:

```bash
uv venv --python 3.13
source .venv/bin/activate
uv pip install psynet          # thin bootstrap only
psynet setup                   # scaffolds files, pins, constraints, install
```

`psynet setup` is the default path: it creates missing boilerplate (including
`.cursor/skills/psynet/` when absent), pins PsyNet, ensures `constraints.txt`,
installs the experiment runtime (`psynet[experiment]`), and initializes Git when
needed. The first `psynet debug`, `psynet test`, or deploy command after setup
stops once if PsyNet created `deploy.toml`; review
`dallinger deployment-files list` and rerun. Git-ignored files may still be
deployed after that review. After setup, use `psynet debug local --docker`
when the experiment should run in Docker mode.

When splitting logic out of `experiment.py`, follow
`develop-experiment-back-end/SKILL.md`: import sibling modules with
`from . import my_module`.

**3. Optional: editable PsyNet checkout (contributors)**

Skip this step unless you are changing PsyNet itself alongside the
experiment. When developing against an editable checkout (for example
`~/PsyNet`), keep a **dedicated** experiment `.venv` (do not sync into the
checkout's own `.venv`):

```bash
uv pip install -e ~/PsyNet
psynet setup --psynet-source editable
```

The initial editable install may be thin bootstrap only (`click`); `psynet setup`
rewrites `requirements.txt` to `-e file://...#egg=psynet[experiment]` and syncs
`constraints.txt` so the experiment runtime lands in the dedicated venv.

If setup already ran and you only need missing files later,
`psynet scripts scaffold` is enough. Use `psynet scripts update` only when you
intentionally want to refresh managed templates/skills from the installed
PsyNet. Do not treat `scripts update` as a substitute for first-time setup.

**4. After setup**

- Confirm `psynet --version`, then `psynet services ensure` (or let
  `psynet debug` / `psynet test local` ensure services).
- Launch with `psynet debug local` or validate with `psynet test local`.

**One local experiment at a time**

Local PsyNet experiments share port 5000, the database, Redis and Dallinger's
development folder, and starting one stops the other's workers. Before each
`psynet debug local`, `psynet test local` or `psynet audit simulate`, check that
nothing else is listening on port 5000 (`lsof -nP -iTCP:5000 -sTCP:LISTEN`).
If another experiment is running, ask the user to stop it rather than stopping
it yourself, and record the wait in the audit timeline. `psynet deploy`
commands also clear the local database and Redis, so don't run them while a
local experiment is running. If local data disappears unexpectedly, check
`ps` for a `psynet deploy` in another session before debugging your code.

#### Coding

- Build a minimal runnable experiment first, then add complexity.
- Develop front end and back end components as relevant,
  using the `develop-experiment-front-end` and `develop-experiment-back-end` skills.
  Write participant-flow Playwright tests with `playwright-testing`.
- Add short comment where the PsyNet pattern is not obvious.
- Where possible, keep the implementation close to PsyNet's native style.
  Prefer built-in pages, controls, events, chatrooms, grouping, and timeline
  constructs over bespoke browser scripts. If custom JavaScript is unavoidable,
  keep it small, isolated, and justified by a requirement that PsyNet cannot
  express natively.
- For websocket or other live multi-participant interactions within one trial,
  use the `realtime-synchronous-experiments` skill alongside this general
  implementation workflow.
- Put pregenerated public media in `static/` and pass `/static/...` URLs to
  prompts (`psynet.media.static_url_for`). Use PsyNet assets for recordings
  and generated files.
- Don't default to `MainConsent` or another built-in consent form: each names
  the institution it was written for (`code/participants/consent`). Unless the
  user names the form to use, write a custom consent page with clearly marked
  placeholder text, and list "replace the placeholder consent with the
  institution's ethics-approved text" as a pre-deployment item in
  `audit/REPORT.md`.
- Once the timeline's time estimates are set, run `psynet estimate` and set
  the recruiter's listing in `config.txt` from it: for Prolific,
  `prolific_estimated_completion_minutes` and a `base_payment` that gives at
  least `wage_per_hour` for that time (`code/participants/payment`). The
  scaffolded values are placeholders.

### Run simulations

Use `psynet audit simulate` to simulate participants and produce an example dataset.
This dataset should contain a decent number of participants representative of a real study;
adjust `Exp.test_n_bots` to ensure this. From the experiment root:

```bash
psynet audit simulate
```

The command writes the only export to
`audit/simulate/analysis/simulated_export/` and marks `simulate_export`
present.

For profile design, data-path parity, mock-LLM patterns, and simulation
limitations, follow `simulate-participants/SKILL.md`.

### Develop analysis scripts

Write scripts to analyze the generated data. Use a Jupyter notebook for this,
with the canonical filename `audit/simulate/analysis/analysis.ipynb`.
The notebook should be self-contained for review, including all code, tables,
and plots.
If the implementation is inspired by a published paper, replicate the analyses reported in the paper as closely as possible.

The analysis-notebook tooling is not part of `psynet[experiment]`. Add the
packages the notebooks use to `requirements.txt` and rerun `psynet setup`,
which relocks `constraints.txt` and installs them. Do not `uv pip install` them
ad hoc: the next `psynet setup` synchronizes `.venv` with `constraints.txt` and
removes unlisted packages (see `code/project/dependencies`). The same applies to
statistics packages: `psynet[experiment]` doesn't include SciPy or statsmodels,
so add `scipy` or `statsmodels` too if the analysis or design simulation needs
them. Deployments install these packages too, which only makes the image larger.

```text
# requirements.txt, below the PsyNet pin
plotly
jupyter
nbconvert
nbformat
ipykernel
```

Then execute the notebook headlessly so its outputs are embedded for review:

```bash
psynet setup
# nbconvert uses the notebook directory as cwd; resolve data paths from the
# experiment root (for example Path(__file__) is unavailable in notebooks—
# walk parents until experiment.py is found, or pass an absolute data path).

jupyter nbconvert --to notebook --execute --inplace audit/simulate/analysis/analysis.ipynb
```

Write, plot and check the notebook as described in
`produce-experiment-audit/references/populating-an-audit.md` ("Writing
notebooks for readers", "Analysis and reporting" and "Figure layout for
rendered audits").

### Review

Review the outcomes of the previous steps and identify any serious issues that need to be addressed.
Return to previous steps if necessary to address these.

### Final report

Compile a final report of the experiment (`audit/REPORT.md`), summarizing the
process taken and any findings that arose. This is the core audit report section.
When a temporary public preview is needed, use `public-tunnel`.

### Completion gate

Do not treat an experiment implementation as complete until the simulation
export, canonical analysis notebook, and `audit/REPORT.md` are present, or until a
blocker for each missing artifact is recorded honestly:

- From the experiment root, update `audit/audit.json` (prefer
  `psynet audit mark-present <artifact_id>`) and record blockers in the audit
  packet. Validate and render with `psynet audit validate` / `psynet audit render`
  from the experiment directory (packet is `./audit/`). See `produce-experiment-audit`.
- Offer to open the rendered audit for the human: run
  `psynet audit serve --render`, share the local URL, and leave the server
  running. Do not ask the human to remember or type that command.

Closing the audit packet is inventory and bookkeeping, not a second evidence
campaign. Do not re-run performance tests, simulations, or other expensive
checks solely because the audit skill checklist mentions them when review-ready
files already exist.
