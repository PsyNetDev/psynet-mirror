---
name: implement-experiment
description: A structured process for implementing PsyNet experiments, including planning, simulations, analysis, and reporting. Use when implementing a PsyNet experiment from a natural-language specification.
compatibility: Requires editable PsyNet at ~/PsyNet, PostgreSQL, Redis, Heroku CLI, and matplotlib/jupyter for executed analysis notebooks.
---

# Implement PsyNet experiments

## Prerequisites

- Use the `explore-psynet-repository` skill before starting.
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

When a temporary public preview is needed, use `prepare-experiment-tunnel`
(and `public-tunnel`).

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

Canonical human docs: `~/PsyNet/docs/experiment_development/agentic_programming.rst`
and `~/PsyNet/psynet/resources/experiment_scripts/AGENTS.md`.

**1. Choose a starting point**

- Prefer copying an authored PsyNet demo (or a prior experiment) into a new
  directory **outside** the PsyNet package tree (for example
  `~/psynet-experiments/<name>/` or a challenge `code/<experiment_slug>/`).
  Bundled demos ship authored files only (`experiment.py`, `requirements.txt`,
  assets); boilerplate and `constraints.txt` are intentionally omitted.
- Or start from an empty directory with a valid Python package name (not
  `code`, not names that cannot be imported).
- Use `explore-psynet-repository` to pick the closest demo before copying.

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

**3. Editable local PsyNet (agents / contributors)**

When developing against an editable `~/PsyNet` checkout, keep a **dedicated**
experiment `.venv` (do not sync into `~/PsyNet/.venv`):

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

The analysis-notebook tooling is not part of the PsyNet editable install. Install
it into the PsyNet virtualenv before executing the notebook, and execute it
headlessly so its outputs are embedded for review:

```bash
uv pip install matplotlib plotly jupyter nbconvert nbformat ipykernel
# nbconvert uses the notebook directory as cwd; resolve data paths from the
# experiment root (for example Path(__file__) is unavailable in notebooks—
# walk parents until experiment.py is found, or pass an absolute data path).

jupyter nbconvert --to notebook --execute --inplace audit/simulate/analysis/analysis.ipynb
```

Prefer inline SVG outputs for plots. Configure the notebook’s plotting backend
accordingly, and use `plt.show()` or an equivalent display call so the plots
actually appear in the executed notebook. For matplotlib in Jupyter:

```python
%config InlineBackend.figure_formats = ["svg"]
import matplotlib.pyplot as plt
# ... plot ...
plt.show()
```

Keep the executed notebook small (many review tools truncate large inline file
content above ~100KB, which breaks notebook rendering). SVG plots stay sharp
without large raster payloads; link out figures that would still bloat the file.

### Review

Review the outcomes of the previous steps and identify any serious issues that need to be addressed.
Return to previous steps if necessary to address these.

### Final report

Compile a final report of the experiment (`audit/REPORT.md`), summarizing the
process taken and any findings that arose. This is the core audit report section.
When a temporary public preview is needed, use `prepare-experiment-tunnel`.

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
