---
name: precision-estimation
description: Implement the default PsyNet design-simulation method, full trial-level Monte Carlo precision estimation, inside audit/simulate/design/core.py. Use when power-analysis has selected precision estimation; it defines estimands, simulates complete experiments, and computes margin-of-error results, but leaves costing, the notebook and review to power-analysis.
---

# Precision estimation

This skill implements the method step of the `power-analysis` workflow:
it turns the planned analysis into estimands, simulates complete
experiments with the shared response model, and writes precision results.
Follow `power-analysis` for everything around it. For an adaptive design,
also follow `make-experiment-adaptive`.

The concepts and code this skill relies on are in the `power-analysis`
references:

- [power-analysis/references/design-simulation-method.md](../power-analysis/references/design-simulation-method.md):
  estimands, precision measures, the default criterion, and what to simulate
  ("Precision and power" and "What to simulate");
- [power-analysis/references/design-simulation-setup.md](../power-analysis/references/design-simulation-setup.md):
  `config.toml`, `core.py`, seeding, parallelism, and the results columns and
  formulas.

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i --no-ignore "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

- `test/audit_reference` — "Design simulation": the audit artifacts `core.py` produces
- `test/audits` — where the design simulation sits in an audit

## Procedure

1. **Define the estimands.** For each primary target, write down in
   scientific language the question, the estimand, how its true value is
   read from the response-model parameters, the planned estimator, and what
   is redrawn between replicates (participants always; stimuli, items or
   groups when the claim generalizes beyond them). Confirm these with the
   user before coding. Use one coherent response model for all targets in a
   scenario.
2. **Set the design grid** densely enough to show where the criterion is
   first met. If an adaptive policy stops early, disable stopping for
   matched-budget cells or report `mean_n_observations` beside every
   precision metric.
3. **Implement `core.py`** as in "Simulation script" of the setup
   reference: one small class
   per target, trial-level replicates from `sample_responses`, the estimator
   planned for the real data (statsmodels by default), deterministic
   scenario seeds, one `loky` job per scenario sharing its replicates across
   targets, one numerical thread per worker. Do not run PsyNet, browsers or
   `psynet test local` per replicate, and do not substitute analytical
   formulas, coefficient-level proxies or rejection rates for the planned
   analysis. Vectorize only where the estimator stays the same; never change
   the estimator for speed. Count failed fits.
4. **Smoke-run** with `n_jobs = 1` and few replicates. Check recovery, bias,
   interval coverage when the estimator produces intervals, and fit
   failures. Fix problems before the full grid.
5. **Compute the results** with the formulas in "Results table" of the setup
   reference.
   Unless the user chose another criterion, set `decision_metric =
   "standardized_margin_of_error"`, `decision_threshold = 0.20` at 95%
   confidence, with one `reference_sd` for all scenarios (never each
   scenario's own noise SD), and fill `decision_value` and `meets_requirement` for every
   primary estimand. For a profile, use the maximum pointwise margin and
   bootstrap its Monte Carlo interval. When `keep_replicates` is true, also
   save replicate-level estimates as Parquet.
6. **Check Monte Carlo error.** If it could change the selected design,
   raise the common replicate count and rerun.
7. **Return to `power-analysis`** with `results.csv` and `run.json`
   (including seed, replicate count, worker count, response parameters and
   response-model hash) for costing, the notebook and the review. In the
   notebook, plot standardized margin of error against participants with
   the 0.20 line and a Monte Carlo ribbon.
