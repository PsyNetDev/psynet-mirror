---
name: make-experiment-adaptive
description: Specify, implement, simulate and validate a PsyNet experiment in which accumulated responses decide later measurements or assignments, such as staircases, adaptive tests, active learning, or adaptive allocation. Use when earlier answers should choose what a participant, or a later participant, is given next.
---

# Make an experiment adaptive

Use this skill when earlier responses should decide what a participant, or a
later participant, is given next. It takes an adaptive design from
specification to a tested PsyNet implementation: classify the procedure, agree
every design decision with the user, write and test the policy, wire it into
PsyNet, simulate it against a non-adaptive baseline, and validate it with bots.

This skill has three references:

- [references/adaptive-design.md](references/adaptive-design.md): kinds of
  adaptivity, the PsyNet building blocks, the specification decisions, where
  the state lives, stopping, decision records, simulation, risks, and the
  review checklist.
- [references/adaptive-implementation.md](references/adaptive-implementation.md):
  project layout and code patterns, walking through
  `demos/features/trial_cue_adaptive`.
- [references/benchmark-adaptive-procedure.md](references/benchmark-adaptive-procedure.md):
  how to compare the adaptive policy with a non-adaptive baseline in the
  design simulation.

## Read first

Read these pages before acting. The "Documentation" section of the experiment's `AGENTS.md` explains how to find and search them.

- `code/writing_a_trial_maker` — "Trials without a trial maker" (`Trial.cue`, `on_trial_created`, `creation_context`) and the node selection hooks
- `code/writing_a_timeline` — page makers, `while_loop` time credit and limits, async code blocks and scheduled tasks
- `design/chains` and `code/writing_a_chain_experiment` — chains, staircases, and the chain selection hooks
- `code/project/classes_and_sqlalchemy` — custom tables and trial columns
- `test/audits` and `test/audit_reference` — the design-simulation section

Also use `power-analysis/SKILL.md` for the design simulation and
`participant-response-models/SKILL.md` for `response_model/`.

## 1. Classify the procedure

Tell the user which kind of adaptivity the request is (within-participant,
across-participant, or combined; see "Kinds of adaptivity" in the design
reference) and what it estimates. Propose the PsyNet building block: a
staircase trial maker, a chain, a `Trial.cue` loop, or custom trial-maker
selection. Prefer a `Trial.cue` loop for a custom within-participant
procedure, and trial-maker hooks when blocks, performance checks, or
trial-based recruitment are needed.

## 2. Complete the specification

Do not implement until the user has answered every item below, unless they
explicitly ask you to propose a design. If anything is missing, list the open
decisions and wait. If asked to propose, make the smallest coherent proposal
and label each assumption. Each item is explained in "Specification decisions"
of the design reference. Record the agreed answers in `audit/PLAN.md`.

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

Create `adaptive_logic.py` with the selection and stopping functions, using the
layout in "Project layout" of the implementation reference. Write unit tests
for it first, in the style of `tests/isolated/test_trial_cue_adaptive_logic.py`.
Pass an explicit random-number generator to any stochastic function.

Use the same table shapes in the experiment, the simulation, and the analysis:
an observations table (response, `participant_id`, `item_id`, position), a
participants table, and an items table, with unique IDs.

## 4. Wire it into PsyNet

Start from `demos/features/trial_cue_adaptive` for a `Trial.cue` loop, or from
the selection hooks in `code/writing_a_trial_maker` for custom trial-maker
selection. Add a decision table and write each row from `on_trial_created`
("Recording decisions" in the implementation reference). For
across-participant state, add the snapshot table and a background refit
("Where the state lives").

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
the review checklist in the design reference.

## Hand back

Report to the user:

- the agreed specification, and any item still open;
- which PsyNet building block was used, and why;
- measured selection time against the budget;
- the adaptive-versus-baseline comparison, including misspecification
  scenarios, and whether the acceptance criteria were met;
- test results, and any blockers recorded in the audit.

Ask the user to go through the review checklist in the design reference.
