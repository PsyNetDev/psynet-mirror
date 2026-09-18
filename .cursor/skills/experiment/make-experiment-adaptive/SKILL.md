---
name: make-experiment-adaptive
description: Convert an existing PsyNet experiment into an adaptive experiment with model-based trial or network selection.
---

# Make a PsyNet experiment adaptive

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general experiment
  workflow and validation expectations.
- Read `develop-experiment-back-end/SKILL.md` for trial-maker selection
  (`StaticTrialMaker` vs chain-based makers) before changing architecture.
- Read `deploy-experiment/SKILL.md` when persistence, deployment,
  recruitment, or exported data safety matters.
- Read `participant-response-models/SKILL.md` when implementing synthetic
  participant responses for bots or simulations.
- Read `power-analysis/SKILL.md` when choosing an adaptive budget or comparing
  the estimator precision and cost of adaptive and static designs.

## Specification gate

Do not implement an adaptive experiment until the user supplies the specification
below, unless they explicitly ask you to propose a design. If anything is
missing, list the decisions they must make and wait for their answer.

- `y`: the mapping from raw trial answers to model observations. Treat `y` as
  mathematical notation; use clear domain-specific names in the implementation.
- `z`: the mapping from participant or context data to model covariates. Treat
  `z` as mathematical notation; use clear domain-specific names in the
  implementation.
- Adaptive unit: what the policy selects, such as a network, node, condition,
  stimulus, item, block, or trial family.
- Learner model: the likelihood, latent parameters, priors, and relationships
  that the adaptive procedure assumes when learning from `y`, `z`, and the
  adaptive unit.
- Simulation response model: how synthetic participants produce `y` in bots
  and standalone simulations. It may match the learner model or deliberately
  differ from it to test robustness to model misspecification.
- Posterior strategy: how posterior beliefs are fit or sampled.
- Optimization policy: objective and decision rule, such as EIG, expected free
  energy, Thompson sampling, greedy utility, or an early-stopping rule.
- Persistence requirement: whether posterior state should persist or be
  recomputed without durable posterior storage.
- Dependency preference or constraints, if any.

If the user asks for suggestions, make the smallest coherent proposal and label
which choices are assumptions.

The learner model is part of the deployed experiment. The simulation response
model is only a testing assumption: in a real experiment, participants supply
the responses, so there is no controllable or known "actual response model" in
the experiment code.

## Implementation constraints

- Document which implementation fields correspond to observations `y` and
  covariates `z`, and use those domain-specific names consistently in code, logs,
  and exports.
- Ask for or implement explicit mapping logic from raw answers to observations
  and covariates.
- Prefer SQLAlchemy columns for storing these variables. Note that PsyNet's `PythonObject` column
  can be used for complex objects if needed.
- Keep raw answer data available for audit; do not replace it with only the
  transformed model observation.
- Log each adaptive decision: candidate IDs, chosen ID, objective components,
  posterior version or snapshot, data cutoff, and optimizer version.
- When already computed at no extra approximation cost, store the posterior
  predictive summary for `y` as it was used when delivering the trial. For
  binary or other low-dimensional discrete `y`, store the probability mass
  function as a list; for continuous `y`, store only the predictive mean and
  standard deviation. Do not add extra integrals, sampling, or approximation work
  just to produce this record.
- Keep selection code fast enough for the participant response path. Adaptive
  computation should normally take less than 1 second per selection; treat
  computations longer than 2 seconds halfway through an actual deployment as a critical threshold
  that requires simplification, caching, or a different posterior strategy.
- Add timing logs around data loading, posterior fitting/sampling, and objective
  scoring.
- Put the simulation response model in the top-level `response_model/` package
  and use it for scientific bots as well as standalone simulations.
- Put posterior inference and selection policy in `adaptive_logic.py`, imported
  from `experiment.py` and standalone simulations. It may import shared
  likelihood components from `response_model/`; do not duplicate them.
- Implementations should include a concise standalone simulation script (`simulate_procedure.py`) that:
   - Draws responses from `response_model/` and simulates the full adaptive loop
   against a static baseline outside PsyNet.
   - Can draw responses from the learner model or from a deliberately different
   simulation response model to test robustness to misspecification.
   - If an approximate inference scheme is used, check the accuracy of posterior
   estimates in these simulations against a trusted reference appropriate to the
   model. This may be HMC when its assumptions and computational cost are suitable.
   - Runs performance checks (average posterior reconstruction time and average design selection time),
   to detect and isolate performance issues owing to the computations themselves.
   - Produces diagnostics for inference reliability, such as convergence checks,
   simulation-based calibration, or comparison with a trusted reference. Use
   posterior predictive checks separately to assess the model's implications and
   fit to simulated data.
- If performance is insufficient, consider using more approximate sampling methods,
or lowering the number of learning-steps, but always make sure the accuracy does not degrade too much.
- If simulations within psynet are sufficiently slower than simulations outside of psynet, make sure that
performance is not degraded by using inefficient data retrieval techniques when updating the posteriors.
For instance, avoid relying on the VarStore. Optimize the SQL queries retrieving the data.

## Posterior update strategy

Choose one of these strategies explicitly:

1. `from_scratch`
   - Recompute the posterior from all finalized, non-failed relevant trials.
   - Prefer this for correctness, reproducibility, and concurrent participants.
   - Use sufficient-statistic queries or cached immutable data when possible.

2. `warm_start_from_previous_posterior`
   - Initialize fitting from the last persisted posterior, but include all data
     needed to avoid missing observations.
   - Persist posterior snapshots in the database using an appropriate custom
     table.
   - Treat stale snapshots as hints, not proof that data has been incorporated.

3. `online_learning`
   - Avoid by default. Updating from only new data plus the previous posterior can
     silently discount data when concurrent workers start from stale snapshots.
   - Use it only with a single-writer queue, explicit locks, or another auditable
     mechanism proving every observation is incorporated exactly once.

## Dependency selection

- Match dependencies to the chosen model and policy, balancing performance,
  clarity, deployment cost, and future extensibility.
- Prefer a probabilistic programming library in general. This is especially crucial when the model is hierarchical,
  non-conjugate, likely to evolve, or needs reusable posterior predictive
  simulation. Pyro is useful when sophisticated EIG computations strategies are required.
  NumPyro can be used when variational inference is needed but the EIG can be estimated
  through classic methods (Nested Monte-Carlo, Rao–Blackwellization).
- Prefer NumPy/SciPy for trivial conjugate models with closed-form posteriors, such as
  simple Beta-Bernoulli multi-arm bandits.
- If adding dependencies, pin or constrain them using the experiment's normal
  dependency workflow and verify local and deployment compatibility.

## Validation

- Run bot tests or simulations that exercise the adaptive selection path, not
  just the static participant flow.
- Export or query trial data and verify that the documented observation and
  covariate fields, selected adaptive units, posterior references, objective
  components, and any free posterior predictive summaries are present.
- Check that repeated runs with a fixed seed reproduce the same decisions when
  the policy is intended to be deterministic.
- Stress the concurrent case with multiple bots when participants may overlap.
- Review timing logs and fail the design if posterior fitting, objective
  scoring, or DB scans exceed the real-time budget for the participant response
  path.
- Include accuracy and performance diagnostics in your pull requests.
- If you cannot reconcile performance and accuracy requirements in the tests, warn the user.

## Common failures

- Proceeding before the user has specified `y`, `z`, model, posterior strategy,
  policy, and persistence needs.
- Recomputing from every trial with expensive probabilistic programming code
  without timing or scalability checks.
- Do NOT deviate from the modelling or optimization strategy decided by the user.
If there is a performance issue under these choices, the user will make an informed decision
about what to improve.
- Storing core adaptive state only in JSON vars when it should be queryable,
  versioned, or exported as a first-class field.
- Using online learning without concurrency protection.
- Overriding PsyNet's managed trial preparation logic instead of using the
  appropriate selection hook.
