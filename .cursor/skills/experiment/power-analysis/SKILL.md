---
name: power-analysis
description: Plan, run and report a PsyNet design simulation that chooses participant, stimulus and trial counts before data collection, including costs and the audit artifacts. Use when sizing an experiment; it explains the method, selects the implementation (default precision-estimation), and owns the audit/simulate/design/ workflow and human review.
---

# Power analysis

A design simulation runs the planned experiment many times on simulated
participants, analyzes each run with the planned analysis, and shows how
precisely each candidate design would answer the research question and what it
would cost. This skill covers the whole campaign: agreeing the question,
setting up `audit/simulate/design/`, costing, the notebook, the audit
artifacts, and the review with the user.

The method step comes from another skill; unless the user asks for a different
approach, use `precision-estimation`. Simulated responses come from the
response model built with `participant-response-models`. For an adaptive
design, also follow `make-experiment-adaptive`.

This skill has two references:

- [references/design-simulation-method.md](references/design-simulation-method.md):
  the ideas (designs, assumptions and scenarios; response models; precision
  versus power; what to simulate; adaptive stopping; costs; reporting) and the
  review checklist.
- [references/design-simulation-setup.md](references/design-simulation-setup.md):
  the recommended files and code (`response_model/`, `config.toml`, `core.py`,
  `results.csv`, `run.json`, costs, the notebook, and the audit commands).

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

- `test/audit_reference` — "Design simulation": the three audit artifacts and how the section renders
- `test/audits` — where the design simulation sits in an audit
- `test/backend` — bots and `psynet audit simulate`
- `code/participants/payment` — wages and bonuses for costing

## Workflow

1. **Agree the question with the user.** List the primary analysis targets,
   the candidate design factors and ranges, the assumption sets, and the
   required precision (or, when the question is whether an effect exists,
   the smallest effect and required power) and its rationale (see "Designs, assumptions and
   scenarios", "Precision and power" and "Choosing the required precision" in
   the method reference). State which parameter
   values come from pilot data, the literature, or judgment. Keep sample sizes
   in `audit/PLAN.md` provisional until the user has reviewed the results.
2. **Build or reuse the response model** with `participant-response-models`.
3. **Write `config.toml`** as in "Configuration" of the setup reference. Use
   one replicate count for every scenario.
4. **Implement the method in `core.py`** by following the method skill
   (`precision-estimation` by default). Run a smoke configuration with
   `n_jobs = 1` and few replicates before the full grid.
5. **Cost the designs.** Run `psynet estimate --mode both` once for a
   reference design and extrapolate, as in "Costs" of the setup reference.
   Never call it inside the design loop. Do not invent bonuses, recruiter fees
   or attrition rates; include them only when the user or the experiment
   supplies them.
6. **Run the full simulation** from the experiment root. Check that
   `results.csv` has a row for every scenario and primary target, and that
   `run.json` records seeds, hashes and the `psynet estimate` output.
7. **Write and execute `simulation.ipynb`**, following the notebook rules
   below.
8. **Add it to the audit**: `psynet audit mark-present` for
   `simulation_notebook`, `simulation_run` and `simulation_results`, then
   `psynet audit serve --render` and inspect the section.
9. **Hand back to the user**: the smallest designs that meet the criterion,
   nearby alternatives, sensitivity to the assumption sets, costs and what
   they exclude, and every judgment-based parameter value. Ask the user to go
   through the review checklist in the method reference. Update
   `audit/PLAN.md` only after the user picks a design.

## Notebook rules

- Write for a reader who knows the study but not the statistics. Follow the
  order in "Reporting the results" of the method reference: summary,
  assumptions, what the results would look like, one subsection per question,
  details for reviewers. Then follow "Writing notebooks for readers" in
  `produce-experiment-audit/references/populating-an-audit.md`.
- Use Plotly with the `plotly_mimetype` renderer. Put the primary metric in
  its own always-visible figure. Use translucent Monte Carlo ribbons for dense
  curves and error bars only for a few unrelated designs; keep exact bounds in
  hover text.
- Where the simulation allows, report precision at every budget rather than
  only the candidate designs, and do not replot the same curve at only the
  candidate points.
- For an adaptive design, include the selection policy as a design factor in
  this campaign rather than a separate one (see `make-experiment-adaptive`).
  Show the fixed-budget curve with stopping disabled first, then the stopping
  rule's savings next to its precision change, following "Adaptive stopping"
  in the method reference. For adaptive estimate recovery, set
  `[metrics] primary = "rmse"` with `report = ["rmse", "pearson_r", "mae",
  "bias", "mean_posterior_sd", "coverage_95"]`, store metric curves in long
  format, and average correlations on the Fisher-z scale.
- A companion metric figure may use `updatemenus` buttons, built as in
  "Notebook" of the setup reference.
- Verify every figure at the rendered width with `psynet audit serve
  --render`, including every button state and after a resize. Use the overlap
  check in `produce-experiment-audit/references/populating-an-audit.md`.
