---
name: make-experiment-adaptive
description: Implement a PsyNet experiment in which accumulated responses influence later measurements or assignments.
---

# Make an experiment adaptive

An adaptive experiment uses earlier responses to decide what to measure next.
Before implementation, read
[references/adaptive-design-contract.md](references/adaptive-design-contract.md)
and agree its specification gate, posterior strategy, dependencies, and
validation criteria with the user.

Classify the procedure by the level at which its adaptive state is maintained:

| Level | Information used for selection | Examples |
| --- | --- | --- |
| Participant-level adaptation | The current participant's response history and a fixed item or task model | Computerized adaptive testing; psychophysical staircases |
| Study-level adaptation | Accumulated responses shared across participants | Active learning; adaptive experimental design |
| Combined adaptation | Participant-level and study-level state | Online-calibrated adaptive testing |

State separately what the procedure estimates: participant attributes, item
attributes, population parameters, or a combination. The two levels may use
different models and update schedules; do not force them through one generic
state object.

## Layout

Keep the adaptive models and selection policy outside `experiment.py`:

```text
experiment.py
adaptive_logic.py
simulate_procedure.py
item_bank/
└── items.csv
response_model/
├── __init__.py
└── core.py
audit/
└── simulate/
    └── design/
        ├── config.toml
        ├── core.py
        ├── results.csv
        ├── run.json
        └── simulation.ipynb
```

`adaptive_logic.py` contains the fitting and selection functions used by both
PsyNet and the standalone simulation. It must not import PsyNet or SQLAlchemy.
From ``experiment.py`` import it with ``from . import adaptive_logic``.
Standalone ``simulate_procedure.py`` and ``python -m audit.simulate.design.core``
use ordinary top-level imports. Run the design command from the experiment
root so those imports resolve.

`simulate_procedure.py` runs one complete adaptive experiment without starting
PsyNet. It maintains the observation, participant, item, and decision tables;
calls `adaptive_logic.py` to select each assignment; and draws the resulting
response from `response_model/`. This standalone simulation tests the
scientific procedure at scale; `psynet audit simulate` is still needed to test its
integration with the PsyNet timeline, response handling, and export path.

`audit/simulate/design/` follows `power-analysis/SKILL.md`. Its
`simulation.ipynb` includes a **Power analysis** section and the **Adaptive
procedure** comparison described in
[references/benchmark-adaptive-procedure.md](references/benchmark-adaptive-procedure.md).
Keep both in one simulation campaign. Keep the adaptive loop in
`simulate_procedure.py` rather than recreating it in the analysis.

`response_model/` follows `participant-response-models/SKILL.md` and generates
synthetic participant responses. The adaptive model estimates quantities used
for selection, whereas the response model supplies assumed behaviour for
simulations and bots. They may share mathematical components.

## Use three related tables

Use the same three-table boundary in PsyNet, standalone simulations, and
analysis code:

```python
observations
# response | participant_id | item_id | trial_order | ...

participants
# participant_id | condition | ...

items
# item_id | category | difficulty | ...
```

`participant_id` must be unique in `participants`, `item_id` must be unique in
`items`, and observation IDs must refer to rows in those tables. Additional
columns should have domain-specific names. The examples below retain these ID
columns while also using them as the dataframe indexes.

Pass these tables directly to the adaptive functions. Each model may perform
its own joins and convert columns to NumPy arrays, sparse matrices, tensors, or
another numerical representation. Pass an explicit random-number generator
when fitting or selection is stochastic.

## Participant-level adaptation

When item parameters are already calibrated, load the immutable item table once
per server process and retain its stable item-ID mapping. Put the file in
``item_bank/`` and commit it so verification and deploy copies include it.
Stock ``deploy.toml`` omits ``data/``, ``audit/``, and ``exports/``; those
directories are for local data, the review packet, and generated exports,
not for runtime tables.

```python
from pathlib import Path

import pandas as pd

ITEMS = pd.read_csv(
    Path(__file__).resolve().parent / "item_bank" / "items.csv"
).set_index("item_id", drop=False)
```

Selection normally updates one participant estimate and scores the remaining
items:

```python
participant_observations = observations[
    observations["participant_id"] == participant_id
]

participant_fit = fit_participant_model(
    observations=participant_observations,
    participant=participants.loc[participant_id],
    items=ITEMS,
)

utilities = score_items(
    participant_fit=participant_fit,
    candidate_items=candidate_items,
)
```

This calculation can normally remain in the participant-facing path. Recompute
the participant estimate from their finalized responses, or treat a cached
estimate as an optimization rather than the authoritative record. Shared item
exposure constraints introduce study-level state and should use the safeguards
below.

## Study-level adaptation

When item or population parameters are learned during collection, responses
from one participant can affect later participants. Fit the shared model from
all three tables, then score the currently available items or assignments:

```python
study_fit = fit_study_model(
    observations=observations,
    participants=participants,
    items=items,
)

utilities = score_items(
    study_fit=study_fit,
    candidate_items=candidate_items,
    participant=participants.loc[participant_id],
)
```

Omit `participant` when the study-level policy is not participant-specific. A
policy that selects recruitment strata or item-participant pairs can construct
a separate candidate table with one row per possible action.

Fit inline only when profiling shows that fitting and scoring remain comfortably
within the experiment's participant-facing latency budget. Otherwise, fit in a
background process and publish immutable, versioned study-model snapshots.
Trial selection should read the latest complete snapshot rather than wait for
or read a partially written update.

Record the response-data cutoff in every snapshot. Allow only one refresh to
claim a given update, and use a single-writer queue or database locking for truly
incremental learning. A warm start is only a starting value; the new fit must
still incorporate responses added since the previous snapshot.

Choose and document the refresh rule, such as a fixed number of new responses
or a fixed interval. Using a stale but valid snapshot, waiting for a refresh, or
falling back to a prespecified allocation policy are different experimental
designs and must not be selected silently at runtime.

## Combine both levels

Keep participant-level and study-level state distinct. For example, an
online-calibrated test can estimate the current participant from their own
responses while taking item parameters from the latest shared calibration
snapshot:

```python
study_fit = latest_study_fit()
calibrated_items = apply_calibration(items, study_fit)

participant_fit = fit_participant_model(
    observations=participant_observations,
    participant=participants.loc[participant_id],
    items=calibrated_items,
)

utilities = score_items(
    study_fit=study_fit,
    participant_fit=participant_fit,
    candidate_items=candidate_items,
)
```

Record both the participant-history cutoff and the shared snapshot version used
for each decision. The two update loops may run at different frequencies and
should be reproduced separately in simulation.

## Connect the policy to PsyNet

We generally recommend constructing adaptive paradigms using `Trial.cue`.
This gives more flexibility than the classic `TrialMaker` options,
such as `StaticTrialMaker` and `ChainTrialMaker`.

A runnable participant-level example is
``demos/features/trial_cue_adaptive``: a 1-up/1-down staircase with
``while_loop``, ``Trial.cue``, and a decision table. Use that layout when
you do not need study-level snapshots or media. The example below is the
same wiring with module-level audio assets.

### Cue the selected candidate

Selection is an ordinary function in the timeline. Keep one cached file per
sound; the trial only receives the two it needs.

```python
from psynet.asset import asset
from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
from psynet.timeline import Module, for_loop
from psynet.trial.main import Trial

from . import adaptive_logic


class AdaptiveTrial(Trial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        return ModularPage(
            "pair",
            AudioPrompt(self.assets["stimulusA"], "Which sound do you prefer?"),
            PushButtonControl(["First", "Second"]),
            time_estimate=self.time_estimate,
        )


def get_assets():
    return {
        stimulus["name"]: asset(stimulus["path"], extension=".mp3", cache=True)
        for stimulus in list_stimuli()
    }


def select_and_cue_pair(trial_index, participant, experiment):
    snapshot = latest_ready_snapshot()
    a, b = adaptive_logic.select_pair(
        study_state=snapshot.state,
        candidate_pairs=pairs_not_seen_by(participant),
    )
    return AdaptiveTrial.cue(
        definition={"stimulus_a": a, "stimulus_b": b},
        assets={
            "stimulusA": pairwise.assets[a],
            "stimulusB": pairwise.assets[b],
        },
        on_trial_created=record_decision,
        creation_context={
            "selected_candidate_id": f"{a}__{b}",
            "study_fit_id": snapshot.id,
            "data_version": snapshot.data_version,
        },
    )


pairwise = Module(
    "audio_pairs",
    for_loop(
        label="adaptive pairs",
        iterate_over=range(N_TRIALS),
        logic=select_and_cue_pair,
        time_estimate_per_iteration=AdaptiveTrial.time_estimate,
    ),
    assets=get_assets,
)
```

`select_and_cue_pair` runs after the module exists, so it can look up cached
files on `pairwise`. `for_loop` passes the iterated value as the first argument
and supplies `participant` and `experiment` by name. Do not upload a new asset
for the pair itself.

`on_trial_created` runs inside the trial-creation transaction, so the decision
row and the assignment commit or roll back together. Follow
[references/study-state-storage.md](references/study-state-storage.md).

Repeat suppression and extra eligibility rules are ordinary filters on the
candidate table. Apply them to the decision table rather than inferring
exposure from successful observations:

```python
seen_pair_ids = decisions.loc[
    decisions["participant_id"] == participant_id,
    "selected_candidate_id",
]
candidate_pairs = pairs[~pairs["pair_id"].isin(seen_pair_ids)]
```

## Implement a custom stopping rule

Put participant-level stopping logic in `adaptive_logic.py` so PsyNet and
`simulate_procedure.py` call the same function. A typical rule combines a
minimum amount of data with a required precision; the exact inputs and return
criterion should use domain-specific names.

A fixed `range(N_TRIALS)` is right for a fixed test length. When the length
depends on the responses, replace `for_loop` with `while_loop`:

```python
while_loop(
    label="adaptive pairs",
    condition=lambda participant: not adaptive_logic.should_stop_participant(
        participant_fit=current_participant_fit(participant),
        n_administered=n_trials_so_far(participant),
    ),
    logic=PageMaker(
        lambda participant, experiment: select_and_cue_pair(
            n_trials_so_far(participant), participant, experiment
        ),
        time_estimate=AdaptiveTrial.time_estimate,
    ),
    expected_repetitions=MAX_TRIALS,
)
```

`while_loop` takes elts rather than a callable, so wrap the selection function
in a `PageMaker`, which resolves to the cued trial each iteration. Unlike
`for_loop` it passes no iteration value, so derive the trial index from the
participant's trial count.

Always cap the loop, either with a hard maximum inside the condition or with
`max_loop_time`. A precision criterion can fail to trigger on unusual response
patterns. `expected_repetitions` only informs progress and reward estimates;
use the same cap as the stopping rule so those estimates are not too low.

Avoid fitting the participant model twice for stopping and selection when that
cost is material; share a fit keyed by the finalized observation set.

## Store observations and decisions

An observation and a decision answer different questions. The observation says
what happened on a trial. The decision says why that trial was assigned. Store
both:

```text
decision -> assigned trial -> raw answer -> model-ready observation
```

PsyNet already stores the browser answer in `trial.answer`. Preserve this as the
authoritative response. When it already has a scientifically meaningful form,
put it directly into the observation table. A seven-point rating does not need
to be called a score.

For a small dataset, unpack `trial.answer` and `trial.definition` in Python.
If fitting rereads a large trial table, store model fields as queryable columns.
Extra columns on a trial class use ordinary SQLAlchemy syntax:

```python
from sqlalchemy import Column, String

from psynet.trial.static import StaticTrial


class VocabularyTrial(StaticTrial):
    item_id = Column(String, index=True)
```

Trial classes share Dallinger's ``info`` table, so two trial classes declaring
the same column name share one column and must agree on its type.

A dedicated observation table remains appropriate when the same fields are
shared with standalone simulation code, or when the model rereads observations
far more often than trials. Follow
[references/study-state-storage.md](references/study-state-storage.md) for
snapshot and decision tables.

Only finalized, non-failed trials belong in the observation table. Select those
columns directly. PsyNet stores the zero-based `Trial.position`, so it can be
copied onto the observation row without another query.

When the outcome genuinely represents correctness or participant performance,
use PsyNet's existing scoring interface:

```python
class AccuracyTrial(StaticTrial):
    def score_answer(self, answer, definition):
        return float(answer["selected_option"] == definition["correct_option"])
```

PsyNet saves that result as `trial.score`, so an accuracy model can use it as
its observation. Do not use `score_answer` merely to obtain a convenient
numeric encoding for a rating or choice with no performance interpretation.

Explicit columns are most useful for fields read repeatedly, expensive derived
outcomes, and results of asynchronous processing. Prefer domain-specific names
such as `rating`, `response_time_seconds`, or `estimated_threshold` over a
generic `model_response`.

Create each decision record when selection occurs, not after the participant
answers. Follow
[references/study-state-storage.md](references/study-state-storage.md) for the
table schema and transactional `on_trial_created` example. Keep diagnostics
compact unless reconstructing the full candidate set is scientifically
necessary.

Finalized responses remain the source of truth for study-level adaptation.
Publish fitted study state as immutable snapshots in a dedicated table, and let
selection use only snapshots marked ready. Small scoring state can live in a
`PythonObject` column; larger state can be stored as an `ExperimentAsset`
referenced by the snapshot. Follow `references/study-state-storage.md` when
implementing this persistence boundary.

Time database loading, model fitting, and candidate scoring separately. Cache
immutable item features and vectorize candidate scoring before changing the
scientific policy. Any shortlist, approximation, or batched update changes the
implemented policy and must be included in planning and simulation.

## Simulate the full procedure

`simulate_procedure.py` should run the adaptive loop without starting PsyNet. It
draws responses from `response_model/`, calls the table-based selection code,
and supports both adaptive and prespecified non-adaptive policies.

Benchmark the adaptive policy against at least one credible non-adaptive
alternative under matched response draws and resource budgets. Evaluate recovery
at prespecified test-length or data-budget checkpoints, including line plots of
the correlation between model estimates and oracle values. Report bias and
error alongside correlation, and separately compare stopping length, exposure,
latency, and other design costs.

Repeat the comparison under plausible misspecification by changing the response
model while leaving the adaptive learner unchanged. Follow
[references/benchmark-adaptive-procedure.md](references/benchmark-adaptive-procedure.md)
for baseline matching, checkpoint metrics, plots, robustness scenarios, and
saved artifacts. Fold those policy comparisons into the power-analysis
simulation rather than running a second Monte Carlo campaign; use
`power-analysis/SKILL.md` for sample size, cost, and the inferential decision.

## Validate in PsyNet

Run bots through the adaptive selection path. Use concurrent bots when the
design has shared model state or exposure constraints. Verify from exported
data that decisions use the recorded item-bank or model version and refer
only to finalized observations available at their cutoff. When the policy is
intended to be deterministic, a fixed simulation seed should reproduce the same
selections.
