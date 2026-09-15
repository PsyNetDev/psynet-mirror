# Benchmark an adaptive procedure

Ask whether adaptation improves estimation or decision quality enough to
justify its complexity. Put that comparison in the **Adaptive procedure**
section of `audit/simulate/design/simulation.ipynb`. Treat policy as a design
factor in the same campaign as the power analysis.

Power analysis asks whether a chosen design meets a prespecified inferential
requirement. Benchmarking supplies the policy comparison that decision needs.

## Define the target and oracle

State which quantities the adaptive model estimates and which simulated truths
are their oracle values. Examples include participant abilities, item
parameters, population effects, and optimal assignments. Preserve stable IDs so
each estimate can be joined to its oracle without positional assumptions.

Choose evaluation checkpoints before running the benchmark. For a
participant-level procedure, these are normally numbers of administered items.
For a study-level procedure, use cumulative finalized observations,
participants, or another deployed update budget.

Variable stopping can otherwise bias comparisons toward participants who remain
in the test. Run two complementary evaluations:

1. a fixed-budget diagnostic run with stopping disabled, used to compare
   estimate trajectories at common checkpoints; and
2. a deployed-policy run with the real stopping rule, used to compare terminal
   accuracy, realized test length, and cost.

Do not compute later-checkpoint accuracy only among cases that happened not to
stop unless that conditional population is itself the stated target.

## Use a credible non-adaptive baseline

Compare against at least one prespecified policy that an experimenter could
realistically deploy, such as random sampling without replacement, stratified
random sampling, or a fixed form. Give the baseline the same item bank,
eligibility rules, response model, participants, and maximum resource budget as
the adaptive policy.

Compare policies within the same simulated worlds and, where valid, use common
random numbers. Pairing should preserve the same latent participants, items,
and environmental conditions without pretending that responses to different
assigned items are identical. Report paired adaptive-minus-baseline differences
within each replicate.

Make both of these comparisons when adaptive stopping is part of the design:

- accuracy at the same test length or accumulated data budget; and
- accuracy and cost under each policy's actual stopping rule.

This distinguishes gains from better selection from gains obtained merely by
using more observations.

## Measure recovery over test length

At every checkpoint, join estimates to oracle values and compute recovery
metrics within each replicate. Include:

- Pearson correlation between estimates and oracle values;
- root mean squared error and mean absolute error;
- mean bias and, when useful, calibration intercept and slope;
- interval coverage when the model produces uncertainty intervals; and
- fit failures and the number of estimable units.

Add rank correlation when ranking is a scientific target. Correlation alone is
not enough: it is invariant to some serious scale and location errors. Do not
pool entities across simulation replicates before computing correlations,
because between-replicate variation can inflate recovery. Summarize replicate
correlations using Fisher's z transform and show Monte Carlo uncertainty.

The primary figure should be a line plot with test length or data budget on the
x-axis and estimate-oracle correlation on the y-axis. Use one line per policy,
uncertainty ribbons across replicates, and facets for the estimation target and
misspecification scenario. Add corresponding error plots, especially RMSE,
rather than interpreting the correlation plot by itself.

Also record outcomes that adaptation can redistribute or worsen: item exposure,
content coverage, subgroup accuracy, stopping length, model-update time,
selection latency, and total computational or participant cost. Compare these
at matched budgets and, where relevant, as an accuracy-cost frontier.

## Test robustness to misspecification

Keep the adaptive learner and policy fixed while changing the data-generating
response model. Include the well-specified case plus a small set of plausible,
scientifically motivated departures. Depending on the task, these may include:

- shifted or heavy-tailed participant and item distributions;
- noisy, drifting, or biased pre-calibrated item parameters;
- guessing, lapses, response styles, or bounded-response effects;
- multidimensional traits or local dependence ignored by the learner;
- differential item functioning or subgroup distribution shift; and
- missingness or dropout related to difficulty or latent ability.

Vary parameters over defensible ranges from pilot data, prior studies, or
explicit stress cases. Avoid a large arbitrary factorial grid that obscures the
few assumptions capable of changing the design decision. Do not tune the
adaptive policy separately for each misspecified scenario unless that retuning
is itself a prespecified deployable procedure.

When learner and response model use different parameterizations, define the
scientifically meaningful oracle or pseudo-true projection before simulation.
Do not choose the mapping after seeing which one makes the adaptive policy look
best.

## Save reproducible artifacts

Write the comparison into the design-simulation campaign:

```text
audit/simulate/design/
├── config.toml
├── core.py
├── results.csv
├── run.json
└── simulation.ipynb
```

`config.toml` specifies policies, checkpoints, response-model scenarios,
replicates, seeds, metrics, and acceptance criteria. `core.py` calls the
canonical `simulate_procedure.py` for every policy and scenario. Keep aggregate
checkpoint results in `results.csv`; use an additional Parquet file when
replicate- or entity-level results are too large for CSV.

Key result columns should identify the scenario, policy, checkpoint, target,
metric, estimate, Monte Carlo interval, and paired difference from baseline.
`run.json` records code and configuration hashes, random seeds, package
versions, command, runtime, and dirty Git state. The executed notebook reads
these saved artifacts and contains the reviewable figures; it should not rerun
or silently transform the benchmark.

Set acceptance criteria before inspecting the full results. A useful criterion
states the required adaptive improvement at matched budget and the largest
acceptable degradation under each plausible misspecification scenario. If the
adaptive policy does not improve the relevant accuracy-cost tradeoff, prefer
the simpler non-adaptive design.
