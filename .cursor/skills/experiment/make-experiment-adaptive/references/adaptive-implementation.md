# Adaptive designs: implementation patterns

This page shows how the ideas in [adaptive-design.md](adaptive-design.md)
appear in code. Most examples come from `demos/features/trial_cue_adaptive`, a
1-up/1-down staircase built with `Trial.cue`: the difficulty goes up after a
correct answer and down after a mistake, and the staircase stops after two
reversals or eight trials. To run it from a PsyNet source checkout:

```console
cd demos/features/trial_cue_adaptive
psynet debug local
```

The PsyNet features used here (`Trial.cue` with `on_trial_created` and
`creation_context`, page makers, `while_loop`, the trial-maker selection hooks,
custom tables, async code blocks and scheduled tasks) are documented in the
PsyNet docs pages listed under "Read first" in the skill. The
`adaptive_logic.py` module and the snapshot and decision tables are the demo's
own code, as examples to adapt.

## Project layout

Keep the selection and stopping rules in a separate module beside
`experiment.py`, with no PsyNet or SQLAlchemy imports, so the experiment, unit
tests, and a standalone simulation all call the same code. A typical layout is:

```text
experiment.py
adaptive_logic.py        # selection and stopping rules
item_bank/
    items.csv            # pre-calibrated items, if the design uses them
simulate_procedure.py    # standalone simulation of the whole procedure
response_model/          # how simulated participants answer
audit/simulate/design/   # design simulation, run locally
```

The demo has only `adaptive_logic.py`; the other entries are for larger
designs. From `experiment.py`, import it as a sibling module with
`from . import adaptive_logic`. Standalone scripts run from the experiment
folder can use `import adaptive_logic`. The stock `deploy.toml` leaves out the
`data/`, `audit/`, and `exports/` folders, so files the running experiment
reads, such as an item bank, go elsewhere, for example in `item_bank/`.

In the demo, the whole policy is three small functions in
`demos/features/trial_cue_adaptive/adaptive_logic.py`: `select_difficulty`,
`n_reversals` and `should_stop`, with the item range and caps as module
constants.

## Choosing the building block

**Staircases.** `GeometricStaircaseTrialMaker` runs within-participant
staircases; see "Built-in paradigms" in `code/writing_a_chain_experiment`.
`demos/experiments/staircase_pitch_discrimination` subclasses
`GeometricStaircaseNode` as `PitchDiscriminationNode`.

**Chains.** In a `ChainTrialMaker`, the next node's definition comes from
`ChainNode.make_next_definition`; see `code/writing_a_chain_experiment`.

**Custom selection in the timeline.** Wrap a selection function in a
`PageMaker` that returns `Trial.cue`, and repeat it with `while_loop` (or
`for_loop` for a fixed length). The function reads the participant's history,
asks `adaptive_logic` for the next difficulty, and cues the trial. From the
demo's `experiment.py`:

```python
def select_and_cue(participant, experiment):
    difficulty = adaptive_logic.select_difficulty(trial_history(participant))
    return StaircaseTrial.cue(
        definition={"difficulty": difficulty},
        on_trial_created=record_decision,
        creation_context={"selected_candidate_id": difficulty},
    )
```

PsyNet calls a page maker's function again when the participant moves between
elements inside it and when the page is refreshed (see "When code runs" in
`code/writing_a_timeline`). Only the first call creates the trial, but later
calls repeat the selection work, so keep the function free of side effects. If
selection is expensive, compute it once in a `CodeBlock`, store the result in
`participant.var`, and have the page maker only read it.

**Custom selection in a trial maker.** Override `custom_node_filter` and
`select_node` on a `StaticTrialMaker`, or `custom_chain_filter` and
`select_chain` on a `ChainTrialMaker`. The filter removes candidates the
participant must not receive; the selector ranks the rest and returns one of
them, optionally wrapped in `Selection(value=..., context=...)` so that
`on_trial_created` receives the context as `selection_context`. The rules and
an example are in `code/writing_a_trial_maker`. Score candidates with
`adaptive_logic`, and write the decision record from `on_trial_created`.

## Where the state lives

Recompute within-participant state from the participant's completed trials.
The demo's `trial_history` takes the participant's completed `StaircaseTrial`
objects in creation order and returns a list of `{"difficulty", "correct"}`
dictionaries for `adaptive_logic`.

Use `trial.answer` as the raw response. When the outcome really is correctness
or performance, define `Trial.score_answer` and use `trial.score`; don't use it
just to turn a rating or choice into a number. `trial.position` is the trial's
zero-based position among the participant's trials in the same trial maker or
module.

If fitting reads many trials, store the fields it needs as columns instead of
unpacking `definition` and `answer` in Python. All trial classes share the
`trial` table, so two trial classes that declare the same column name must
declare it the same way (see `code/project/classes_and_sqlalchemy`):

```python
from sqlalchemy import Column, String

class VocabularyTrial(Trial):
    item_id = Column(String, index=True)
```

For across-participant state, publish each fit as a row in a custom table and
never change it after it is marked ready:

```python
@register_table
class StudyModelSnapshot(SQLBase, SQLMixin):
    __tablename__ = "study_model_snapshot"

    status = Column(String, index=True)  # "building", "ready" or "failed"
    model_version = Column(String)
    data_version = Column(Integer, unique=True)
    observation_count = Column(Integer)
    observation_fingerprint = Column(String)
    state = deferred(Column(PythonObject, nullable=True))
    error = Column(String, nullable=True)
```

`SQLBase`, `SQLMixin` and `register_table` come from `psynet.data`, and
`PythonObject` from `psynet.field`. The unique `data_version` means that only
one refit can claim each update: a second attempt to insert the same version
fails. Selection reads the newest ready snapshot:

```python
snapshot = (
    StudyModelSnapshot.query.filter_by(status="ready")
    .order_by(StudyModelSnapshot.data_version.desc())
    .first()
)
```

Keep `state` to what selection needs, such as item estimates and their
uncertainty. Store a larger fit as a `FileAsset` and save its ID on the
snapshot. Run the refit off the participant's request, in an `AsyncCodeBlock`
with `wait=False` or in a `scheduled_task` method on the experiment class, as
`demos/features/bot_2` does. Async code blocks from different participants can
run at the same time, which is why the claim goes through the database.

## Stopping

The demo's `while_loop` asks `adaptive_logic.should_stop` before each trial.
The stopping rule includes the maximum, and `expected_repetitions` is set to
the same maximum:

```python
staircase = Module(
    "staircase",
    while_loop(
        label="adaptive staircase",
        condition=lambda participant: (
            not adaptive_logic.should_stop(trial_history(participant))
        ),
        logic=PageMaker(
            select_and_cue,
            time_estimate=StaircaseTrial.time_estimate,
        ),
        expected_repetitions=adaptive_logic.MAX_TRIALS,
    ),
)
```

`while_loop` gives every participant time credit for `expected_repetitions`
trials by default. `max_loop_time` limits the time in the loop; see
`code/writing_a_timeline`.

## Recording decisions

The demo records each decision in a custom `AdaptiveDecision` table with
`participant_id`, a unique `trial_id` and `selected_candidate_id` columns. The
callback passed to `Trial.cue` writes the row:

```python
def record_decision(trial, creation_context):
    decision = AdaptiveDecision(
        participant_id=trial.participant_id,
        selected_candidate_id=str(creation_context["selected_candidate_id"]),
    )
    decision.trial = trial
    db.session.add(decision)
```

The callback runs in the same transaction as trial creation, so the trial and
its decision are saved or rolled back together. Assign the relationship
(`decision.trial = trial`) rather than the ID, because the trial's ID may not
exist until the transaction flushes.

In a real design, add columns for the candidate pool version, the snapshot ID,
the history count, and the selected utility. `SQLMixin` already provides a
`details` JSON column for small extra diagnostics.

## Testing and simulating

Unit-test `adaptive_logic.py` without starting PsyNet. The demo's tests are in
`tests/isolated/test_trial_cue_adaptive_logic.py`; for example,
`test_stops_at_the_trial_cap_or_two_reversals` checks the stopping rule
directly.

A standalone simulation (`simulate_procedure.py` in the layout above) runs the
complete procedure many times the same way. It keeps its own tables of
observations, participants, and items, calls `adaptive_logic` for each
assignment, and draws the response from `response_model/`. The design
simulation in `audit/simulate/design/` calls it for the adaptive policy and the
non-adaptive baseline, following
[benchmark-adaptive-procedure.md](benchmark-adaptive-procedure.md).

Then run bots through the real experiment with `psynet test local`. The demo's
`Exp.test_check_bot` checks the sequence of difficulties and that every
decision points to its trial. For across-participant designs, also run several
bots at once (see `test/backend`):

```console
psynet test local --n-bots 5 --parallel
```

Check in the exported data that each decision refers to a snapshot or history
that existed when it was made, and that a fixed seed reproduces the same
selections when the policy is meant to be deterministic.
