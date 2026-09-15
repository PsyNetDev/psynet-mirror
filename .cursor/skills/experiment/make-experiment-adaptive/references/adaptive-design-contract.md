# Specify and validate an adaptive design

Use this checklist before implementing the workflow in the main skill. It
preserves the scientific and operational decisions that must be explicit even
when the implementation uses the standard table and snapshot patterns.

## Specification gate

Do not implement an adaptive experiment until the user supplies the
specification below, unless they explicitly ask you to propose a design. If
anything is missing, list the decisions they must make and wait for their
answer.

- `y`: the mapping from raw trial answers to model observations. Treat `y` as
  mathematical notation; use clear domain-specific names in the implementation.
- `z`: the mapping from participant or context data to model covariates. Treat
  `z` as mathematical notation; use clear domain-specific names in the
  implementation.
- Adaptive unit: what the policy selects, such as a network, node, condition,
  stimulus, item, block, or trial family.
- Learner model: the likelihood, latent parameters, priors, and relationships
  assumed when learning from `y`, `z`, and the adaptive unit.
- Simulation response model: how synthetic participants produce `y`. It may
  match the learner model or deliberately differ to test misspecification.
- Posterior strategy: how posterior beliefs are fit or sampled.
- Optimization policy: the objective and decision rule, such as expected
  information gain, Thompson sampling, greedy utility, or early stopping.
- Persistence requirement: whether posterior state persists or is recomputed.
- Dependency preferences or constraints.

If the user asks for suggestions, make the smallest coherent proposal and
label each assumption. The learner model is part of the deployed experiment;
the simulation response model is only a testing assumption.

## Implementation constraints

- Document which fields correspond to observations `y` and covariates `z`.
- Keep raw answers for audit alongside transformed model observations.
- Prefer queryable SQLAlchemy columns for core variables; use `PythonObject`
  only where structured values genuinely require it. Extra ``Column``
  attributes on a trial class are fine, but trial classes share Dallinger's
  ``info`` table, so a shared column name must have one type. Use a dedicated
  observation table when the same schema is shared with standalone simulation
  code.
- Put calibrated item banks in ``item_bank/`` and commit them. Stock
  ``deploy.toml`` omits the experiment-root ``data/``, ``audit/``, and
  ``exports/`` directories. Keep inference and selection code such as
  ``adaptive_logic.py`` beside ``experiment.py`` so it still deploys.
- Record candidate IDs, chosen ID, objective components, model snapshot, data
  cutoff, and optimizer version for every adaptive decision.
- When already available without extra approximation, record the posterior
  predictive summary used for selection.
- Time data loading, posterior fitting, and objective scoring separately.
  Participant-facing selection should normally finish within one second;
  sustained computations over two seconds require redesign or explicit user
  approval.
- Put response generation in `response_model/`, and shared fitting and
  selection logic in `adaptive_logic.py`.
- Keep the standalone simulation independent of PsyNet and SQLAlchemy. Exercise
  the whole adaptive loop against a non-adaptive baseline, test plausible model
  misspecification, and compare approximate inference with a trusted reference
  where appropriate.

## Posterior update strategy

Choose one strategy explicitly:

1. `from_scratch`
   - Recompute from all finalized, non-failed observations.
   - Prefer this for correctness, reproducibility, and concurrent participants.
2. `warm_start_from_previous_posterior`
   - Initialize from the latest snapshot, but still include all required data.
   - Treat a stale snapshot as a hint, not proof that data was incorporated.
3. `online_learning`
   - Avoid by default. Concurrent workers can start from stale snapshots and
     silently omit or duplicate observations.
   - Use only with an auditable single-writer queue, lock, or equivalent
     exactly-once mechanism.

## Dependency selection

- Match dependencies to the model and policy, balancing performance, clarity,
  deployment cost, and likely model evolution.
- Prefer a probabilistic programming library for hierarchical, non-conjugate,
  or evolving models. Pyro is useful for sophisticated expected-information
  gain methods; NumPyro is suitable for variational inference with conventional
  Monte Carlo estimators.
- Prefer NumPy/SciPy for small conjugate models with closed-form posteriors.
- Add dependencies through the experiment's normal dependency workflow and
  verify both local and deployment compatibility.

## Validation

- Exercise the adaptive selection path with bots or simulations.
- Verify exports contain observations, covariates, chosen units, snapshot
  references, objective components, and any recorded predictive summaries.
- Use fixed seeds to check reproducibility where the policy is deterministic.
- Stress concurrent selection when participant sessions overlap.
- Review timing and inference diagnostics. Do not trade away an agreed
  scientific model or policy silently; present performance/accuracy tradeoffs
  to the user.

## Common failures

- Starting before `y`, `z`, the model, posterior strategy, policy, and
  persistence requirements are agreed.
- Repeatedly fitting expensive models from the full trial table without timing
  data access or inference.
- Storing core adaptive state only in unqueryable JSON variables.
- Using online learning without concurrency protection.
- Storing the item bank under ``data/``, ``audit/``, or ``exports/``.

When wiring selection with a trial maker rather than ``Trial.cue``:

- Re-querying a selected node or chain instead of returning the exact candidate
  object supplied by PsyNet.
- Overriding managed trial preparation rather than the relevant discovery,
  eligibility, or selection hook.
- Naming the trial-maker callback parameter ``creation_context``; the maker
  hook is ``on_trial_created(..., selection_context=...)``.
