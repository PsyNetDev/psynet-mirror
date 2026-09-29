Writing an adaptive experiment
==============================

Most examples on this page come from ``demos/features/trial_cue_adaptive``, a
1-up/1-down staircase built with :meth:`~psynet.trial.main.Trial.cue`: the
difficulty goes up after a correct answer and down after a mistake, and the
staircase stops after two reversals or eight trials. To run it from a PsyNet
source checkout:

.. admonition:: What PsyNet provides

   The trial makers, hooks, ``Trial.cue``, page makers and code blocks on this
   page are part of PsyNet. The ``adaptive_logic.py`` module, the snapshot
   table and the ``AdaptiveDecision`` table are defined in the demo's own
   code, as examples to adapt.

A coding agent following the ``make-experiment-adaptive`` skill writes this
code; the details here are for reviewing its work or writing it yourself.

.. code-block:: console

    cd demos/features/trial_cue_adaptive
    psynet debug local

Project layout
--------------

Keep the selection and stopping rules in a separate module beside
``experiment.py``, with no PsyNet or SQLAlchemy imports, so the experiment,
unit tests, and a standalone simulation all call the same code. A typical
layout is:

.. code-block:: text

    experiment.py
    adaptive_logic.py        # selection and stopping rules
    item_bank/
        items.csv            # pre-calibrated items, if the design uses them
    simulate_procedure.py    # standalone simulation of the whole procedure
    response_model/          # how simulated participants answer
    audit/simulate/design/   # design simulation, run locally

The demo has ``adaptive_logic.py``; the other entries are for larger designs.
From ``experiment.py``, import it as a sibling module:

.. code-block:: python

    from . import adaptive_logic

Standalone scripts run from the experiment folder can use
``import adaptive_logic``. The stock ``deploy.toml`` leaves out the ``data/``,
``audit/``, and ``exports/`` folders, so files the running experiment reads,
such as an item bank, go elsewhere, for example in ``item_bank/``.

In the demo, the whole policy is three small functions:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/adaptive_logic.py
   :start-at: ITEMS =

Kinds of adaptivity
-------------------

**Staircases.**
:class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker` runs
within-participant staircases. Subclass
:class:`~psynet.trial.staircase.GeometricStaircaseNode` to set ``k`` (correct
answers needed before the task gets harder), ``step``, and the
``increase_difficulty`` and ``decrease_difficulty`` methods. From
``demos/experiments/staircase_pitch_discrimination``:

.. literalinclude:: ../../demos/experiments/staircase_pitch_discrimination/experiment.py
   :pyobject: PitchDiscriminationNode

The trial maker takes ``max_nodes_per_chain`` and optionally
``max_reversals_per_chain``. At the end, it scores each staircase as the mean
parameter at its reversals and checks it against ``min_passing_score`` and
``max_passing_score`` if you set them.

**Chains.** In a :class:`~psynet.trial.chain.ChainTrialMaker`, the next
node's definition comes from
:meth:`~psynet.trial.chain.ChainNode.make_next_definition`; see
:doc:`writing_a_chain_experiment`.

**Custom selection in the timeline.** Wrap a selection function in a
:class:`~psynet.timeline.PageMaker` that returns
:meth:`~psynet.trial.main.Trial.cue`, and repeat it with
:func:`~psynet.timeline.while_loop` (or :func:`~psynet.timeline.for_loop` for
a fixed length). The function reads the participant's history, asks
``adaptive_logic`` for the next difficulty, and cues the trial:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :pyobject: select_and_cue

PsyNet calls a page maker's function again each time the participant moves
to the next element inside it, and when the page is refreshed. Only the first
call creates the trial, so later calls do not change it. They still repeat
the selection work, however, so keep the function free of side effects. If
selection is expensive, compute it once in a
:class:`~psynet.timeline.CodeBlock`, store the result in ``participant.var``,
and have the page maker only read it.

**Custom selection in a trial maker.** Override the selection hooks of a
:class:`~psynet.trial.static.StaticTrialMaker`
(:meth:`~psynet.trial.static.StaticTrialMaker.custom_node_filter` and
:meth:`~psynet.trial.static.StaticTrialMaker.select_node`) or a
:class:`~psynet.trial.chain.ChainTrialMaker`
(:meth:`~psynet.trial.chain.ChainTrialMaker.custom_chain_filter` and
:meth:`~psynet.trial.chain.ChainTrialMaker.select_chain`). The filter removes
candidates the participant must not receive; the selector ranks the rest. It
must return one of the objects it was given, not a re-queried copy, either
directly or wrapped in a :class:`~psynet.trial.main.Selection` with a
``context``. PsyNet passes that context to
:meth:`~psynet.trial.main.NetworkTrialMaker.on_trial_created` as
``selection_context``:

.. code-block:: python

    class AdaptiveTrialMaker(StaticTrialMaker):
        def select_node(self, nodes, participant, experiment):
            utilities = adaptive_logic.score_items([n.definition for n in nodes])
            best = max(range(len(nodes)), key=utilities.__getitem__)
            return Selection(value=nodes[best], context={"utility": utilities[best]})

        def on_trial_created(self, trial, experiment, participant, selection_context=None):
            decision = AdaptiveDecision(participant_id=participant.id)
            decision.trial = trial
            db.session.add(decision)

``on_trial_created`` runs for primary trials only, not for repeat trials or
the copies given to other members of a synchronized group. Trial makers run
selection once per trial.

Where the state lives
---------------------

Recompute within-participant state from the participant's completed trials.
The demo takes the finished staircase trials in creation order:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :pyobject: trial_history

Use ``trial.answer`` as the raw response. When the outcome really is
correctness or performance, define
:meth:`~psynet.trial.main.Trial.score_answer` and use ``trial.score``. Don't
use it just to turn a rating or choice into a number. ``trial.position`` is
the trial's zero-based position among the participant's trials in the same
trial maker or module.

If fitting reads many trials, store the fields it needs as columns instead
of unpacking ``definition`` and ``answer`` in Python. All trial classes share
the ``trial`` table, so two trial classes that declare the same column name
share one column and must declare it the same way:

.. code-block:: python

    from sqlalchemy import Column, String

    class VocabularyTrial(Trial):
        item_id = Column(String, index=True)

For across-participant state, publish each fit as a row in a custom table
(see :doc:`/code/project/classes_and_sqlalchemy`) and never change it after
it is marked ready:

.. code-block:: python

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

``SQLBase``, :class:`~psynet.data.SQLMixin`, and
:func:`~psynet.data.register_table` come from :mod:`psynet.data`, and
:class:`~psynet.field.PythonObject` from :mod:`psynet.field`. The unique
``data_version`` means that only one refit can claim each update: a second
attempt to insert the same version fails. Selection reads the newest ready
snapshot:

.. code-block:: python

    snapshot = (
        StudyModelSnapshot.query.filter_by(status="ready")
        .order_by(StudyModelSnapshot.data_version.desc())
        .first()
    )

Keep ``state`` to what selection needs, such as item estimates and their
uncertainty. Store a larger fit as a :class:`~psynet.asset.FileAsset` and
save its ID on the snapshot. Run the refit off the participant's request, in
an :class:`~psynet.timeline.AsyncCodeBlock` with ``wait=False`` or in a
method on the experiment class decorated with ``scheduled_task`` from
:mod:`psynet.experiment`, as ``demos/features/bot_2`` does. Scheduled tasks
run in the clock process, whereas async code blocks from different
participants can run at the same time, which is why the claim goes through
the database.

Stopping
--------

The demo's ``while_loop`` asks ``adaptive_logic.should_stop`` before each
trial. The stopping rule includes the maximum, and ``expected_repetitions``
is set to the same maximum:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :start-at: staircase = Module(
   :end-before: class Exp

:func:`~psynet.timeline.while_loop` has ``fix_time_credit=True`` by default,
so every participant gets time credit for ``expected_repetitions`` trials.
``max_loop_time`` limits the time in the loop in seconds; by default,
participants who reach it are sent to the unsuccessful end, unless
``fail_on_timeout=False``.

Recording decisions
-------------------

The demo records each decision in a custom table:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :pyobject: AdaptiveDecision

``select_and_cue`` passes provenance to :meth:`~psynet.trial.main.Trial.cue`
through ``creation_context``, and ``on_trial_created`` writes the row:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :pyobject: record_decision

The callback runs in the same transaction as trial creation. It may take
``trial``, ``experiment``, ``participant``, and ``creation_context``
arguments. If it raises an exception, the trial and the decision are both
rolled back. Assign the relationship (``decision.trial = trial``) rather than
the ID, because the trial's ID may not exist until the transaction flushes.
Passing ``creation_context`` without ``on_trial_created`` raises an error.

In a real design, add columns for the candidate pool version, the snapshot
ID, the history count, and the selected utility. ``SQLMixin`` already
provides a ``details`` JSON column for small extra diagnostics.

Simulating before deployment
----------------------------

Unit-test ``adaptive_logic.py`` without starting PsyNet. The demo's tests are
in ``tests/isolated/test_trial_cue_adaptive_logic.py``:

.. literalinclude:: ../../tests/isolated/test_trial_cue_adaptive_logic.py
   :pyobject: test_stops_at_the_trial_cap_or_two_reversals

A standalone simulation (``simulate_procedure.py`` in the layout above) runs
the complete procedure many times the same way. It keeps its own tables of
observations, participants, and items, calls ``adaptive_logic`` for each
assignment, and draws the response from ``response_model/``. The design
simulation in ``audit/simulate/design/`` calls it for the adaptive policy
and the non-adaptive baseline (see :doc:`/test/design_simulation`).

Then run bots through the real experiment with ``psynet test local``. The
demo's ``test_check_bot`` checks the sequence of difficulties and that every
decision points to its trial:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :pyobject: Exp.test_check_bot

For across-participant designs, also run several bots at once (see
:doc:`/test/backend`):

.. code-block:: console

    psynet test local --n-bots 5 --parallel

Check in the exported data that each decision refers to a snapshot or history
that existed when it was made, and that a fixed seed reproduces the same
selections when the policy is meant to be deterministic.

.. seealso::

   :doc:`/design/adaptive_experiments`, the concept page for this topic, and
   :doc:`/reference/api/trial/main` in the API reference.
