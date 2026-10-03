# Benchmark an adaptive procedure

Put the comparison in the **Adaptive procedure** section of
`audit/simulate/design/simulation.ipynb`, with policy as a design factor in the
same campaign as the power analysis. The concepts are in "Simulating before
deployment" of [adaptive-design.md](adaptive-design.md); this file is the
procedure.

## Before running

1. Name the estimation targets (participant abilities, item parameters,
   population effects, optimal assignments) and their oracle values in the
   simulation. Join estimates to oracles by stable ID, never by position.
2. Fix the checkpoints: numbers of administered items for within-participant
   procedures; cumulative finalized observations or participants for
   across-participant ones.
3. Write acceptance criteria in `config.toml`: the required improvement at a
   matched budget, and the largest acceptable degradation under each
   misspecification scenario.
4. When learner and response model use different parameterizations, define
   the oracle mapping now, not after seeing results.

## Runs

- **Fixed-budget run**, stopping disabled: compares estimate trajectories at
  common checkpoints. Do not compute later-checkpoint accuracy only among
  cases that happened not to stop.
- **Deployed-policy run**, real stopping rule: compares terminal accuracy,
  realized length, and cost.

Give the baseline the same item bank, eligibility rules, participants, and
maximum budget. Use the same simulated worlds for both policies and common
random numbers where valid, and report paired adaptive-minus-baseline
differences within each replicate.

## Metrics

Per checkpoint and replicate: Pearson correlation with the oracle (plus rank
correlation if ranking matters), RMSE, MAE, mean bias, calibration slope and
intercept where useful, interval coverage if the model gives intervals, and
fit failures. Compute correlations within replicates and summarize them with
Fisher's z and Monte Carlo intervals; do not pool entities across replicates.
Also record item exposure, content coverage, subgroup accuracy, stopping
length, update time, and selection latency.

Primary figure: correlation against checkpoint, one line per policy, ribbons
across replicates, facets by target and scenario. Add an RMSE figure beside it.

## Misspecification

Keep the learner and policy fixed; change only the response model. Include the
well-specified case and a few scientifically motivated departures, for
example heavy-tailed distributions, noisy item calibration, guessing or
lapses, ignored multidimensionality, subgroup shift, or dropout related to
difficulty. Avoid a large arbitrary grid, and do not retune the policy per
scenario unless that retuning is itself deployable.

## Artifacts

Follow `power-analysis/SKILL.md` for `config.toml`, `core.py`, `results.csv`,
`run.json`, and `simulation.ipynb`. `core.py` calls `simulate_procedure.py` for
every policy and scenario. Result columns identify scenario, policy,
checkpoint, target, metric, estimate, Monte Carlo interval, and paired
difference from baseline. The notebook reads saved results and does not rerun
the benchmark.

If the adaptive policy does not improve the accuracy-cost tradeoff, recommend
the simpler non-adaptive design.
