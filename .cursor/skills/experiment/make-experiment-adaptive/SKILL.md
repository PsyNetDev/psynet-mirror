---
name: make-experiment-adaptive
description: Implement a PsyNet experiment in which accumulated responses influence later measurements or assignments.
---

# Make an experiment adaptive

Use this skill when earlier responses should decide what a participant, or a
later participant, is given next.

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

- `design/adaptive_experiments` — kinds of adaptivity, the specification, state and snapshots, stopping, decision records, simulation, review checklist
- `code/adaptive_experiments` — project layout, `Trial.cue` loops, trial-maker selection hooks, snapshot tables, decision records, tests
- `code/writing_a_trial_maker` — trial makers and "Trials without a trial maker"
- `design/chains` and `code/writing_a_chain_experiment` — chains and staircases
- `test/audits` and `test/audit_reference` — the design-simulation section

Also use `power-analysis/SKILL.md` for the design simulation and
`participant-response-models/SKILL.md` for `response_model/`.

## 1. Classify the procedure

Tell the user which kind of adaptivity the request is (within-participant,
across-participant, or combined; see "Kinds of adaptivity" in
`design/adaptive_experiments`) and what it estimates. Propose the PsyNet
building block: a staircase trial maker, a chain, a `Trial.cue` loop, or
custom trial-maker selection. Prefer a `Trial.cue` loop for a custom
within-participant procedure, and trial-maker hooks when balancing,
performance checks, or trial-based recruitment are needed.

## 2. Complete the specification gate

Do not implement until the user has answered every item below, unless they
explicitly ask you to propose a design. If anything is missing, list the open
decisions and wait. If asked to propose, make the smallest coherent proposal
and label each assumption. Record the agreed answers in `audit/PLAN.md`.

- [ ] Adaptive unit
- [ ] Observations: mapping from raw answers (`y`)
- [ ] Covariates: participant or context data used by the model (`z`)
- [ ] Learner model: likelihood, parameters, priors
- [ ] Update strategy: from scratch, warm start, or online learning (online
      only with a single-writer mechanism the user accepts)
- [ ] Selection policy, tie-breaking, and eligibility rules
- [ ] Stopping rule and its maximum
- [ ] Across-participant only: refresh rule, and behavior while no new fit is
      ready
- [ ] Response time budget (default: under about one second)
- [ ] Simulation response model and misspecification scenarios
- [ ] Non-adaptive baseline and acceptance criteria
- [ ] Dependencies

`y` and `z` are notation for the conversation; use domain-specific names in
code. For dependencies, prefer NumPy/SciPy for small conjugate models and a
probabilistic programming library (for example NumPyro or Pyro) for
hierarchical, non-conjugate, or evolving models. Add them through the
experiment's normal dependency workflow and check they install in the
deployment image.

## 3. Write and test the policy

Create `adaptive_logic.py` with the selection and stopping functions, using
the layout in "Project layout" of `code/adaptive_experiments`. Write unit tests
for it first, in the style of `tests/isolated/test_trial_cue_adaptive_logic.py`.
Pass an explicit random-number generator to any stochastic function.

Use the same table shapes in the experiment, the simulation, and the
analysis: an observations table (response, `participant_id`, `item_id`,
position), a participants table, and an items table, with unique IDs.

## 4. Wire it into PsyNet

Start from `demos/features/trial_cue_adaptive` for a `Trial.cue` loop, or
from the trial-maker example in "Kinds of adaptivity" of
`code/adaptive_experiments`. Add a decision table and write each row from
`on_trial_created` ("Recording decisions"). For across-participant state,
add the snapshot table and a background refit ("Where the state lives").

Time data loading, fitting, and scoring separately. If selection exceeds the
agreed budget, present the options (caching, vectorizing, background refits,
shortlists, approximations) and their effect on the policy to the user. Do not
change the scientific policy silently.

## 5. Simulate the procedure

Write `simulate_procedure.py`: it runs the complete adaptive loop without
PsyNet, calls `adaptive_logic.py`, draws responses from `response_model/`, and
supports both the adaptive policy and the non-adaptive baseline. Then add the
**Adaptive procedure** comparison to the design simulation, following
[references/benchmark-adaptive-procedure.md](references/benchmark-adaptive-procedure.md),
in the same campaign as the power analysis.

## 6. Validate in PsyNet

Run `psynet test local` with a `test_check_bot` like the demo's. For
across-participant designs, also run parallel bots. Check the export against
"What to check when reviewing" in `design/adaptive_experiments`.

## Hand back

Report to the user:

- the agreed specification, and any item still open;
- which PsyNet building block was used, and why;
- measured selection time against the budget;
- the adaptive-versus-baseline comparison, including misspecification
  scenarios, and whether the acceptance criteria were met;
- test results, and any blockers recorded in the audit.
