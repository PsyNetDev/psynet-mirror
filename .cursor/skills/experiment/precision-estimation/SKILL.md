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
  estimands, precision measures, the required precision, and what to
  simulate ("Precision and power", "Choosing the required precision" and
  "What to simulate");
- [power-analysis/references/design-simulation-setup.md](../power-analysis/references/design-simulation-setup.md):
  `config.toml`, `core.py`, seeding, parallelism, and the results columns and
  formulas.

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

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
   Use the decision metric and threshold agreed with the user, at 95%
   confidence, in the response's units and the same for all scenarios
   ("Choosing the required precision" in the method reference). Fill
   `decision_value` and `meets_requirement` for every primary estimand, or
   leave them empty if the user chose to decide from the curves. For a
   profile, decide on the RMS margin across the set and bootstrap its Monte
   Carlo interval, and also report the largest margins, the profile
   correlation and the smallest spread for a 0.9 correlation. When
   `keep_replicates` is true, also save replicate-level estimates as Parquet.
6. **Check Monte Carlo error.** If it could change the selected design,
   raise the common replicate count and rerun.
7. **Prepare the check after data collection.** Make sure the analysis
   notebook reports the achieved margin of error and, for a profile, the
   split-half reliability ("After data collection" in the method
   reference).
8. **Return to `power-analysis`** with `results.csv` and `run.json`
   (including seed, replicate count, worker count, response parameters and
   response-model hash) for costing, the notebook and the review. In the
   notebook, plot the margin of error, in the response's units, against
   participants with the threshold line and a Monte Carlo ribbon.
