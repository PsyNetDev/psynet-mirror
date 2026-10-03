Writing a static trial maker
============================

Most examples on this page come from ``demos/pipelines/simple_rating``, in
which participants rate instrument sounds on two scales. To run it from a
PsyNet source checkout:

.. code-block:: console

    cd demos/pipelines/simple_rating
    psynet debug local

How it works
------------

Nodes are usually built in a ``get_nodes`` function. Here, one
:class:`~psynet.trial.static.StaticNode` is created per audio file in
``static/instrument_sounds``, and the file's URL is stored in the definition:

.. literalinclude:: ../../demos/pipelines/simple_rating/experiment.py
   :pyobject: get_nodes

The trial is a subclass of :class:`~psynet.trial.static.StaticTrial`. It needs
a ``time_estimate`` in seconds and a ``show_trial`` method that returns the
page. The trial's definition is available as ``self.definition``:

.. literalinclude:: ../../demos/pipelines/simple_rating/experiment.py
   :pyobject: CustomTrial

The :class:`~psynet.trial.static.StaticTrialMaker` goes in the timeline:

.. literalinclude:: ../../demos/pipelines/simple_rating/experiment.py
   :pyobject: get_timeline

What the trial adds
-------------------

Override :meth:`~psynet.trial.main.Trial.finalize_definition`. It receives a
copy of the node's definition and returns the trial's definition. In
``demos/experiments/static``, each trial draws a random text color:

.. literalinclude:: ../../demos/experiments/static/experiment.py
   :pyobject: AnimalTrial.finalize_definition

The method runs once, when the trial is created, so random draws belong here.
Variation that only changes how existing files are presented, such as the
order of response options, needs no new files. To generate a new media file
for each trial, see :doc:`/code/trials/assets`.

For dense paradigms, where each trial samples a stimulus from a continuous
space, :mod:`psynet.trial.dense` provides trial classes that do the sampling,
such as :class:`~psynet.trial.dense.SingleStimulusTrial`. The
``demos/features/dense_color`` demo shows one in use.

Choosing the next node
----------------------

Allocation is set with arguments to
:class:`~psynet.trial.static.StaticTrialMaker`:

- ``expected_trials_per_participant`` and ``max_trials_per_participant``:
  an integer, or ``"n_nodes"`` for one per node.
- ``block_order`` (default ``"random"``) and ``node_order`` (default
  ``"balanced"``); see :ref:`trial_order`.
- ``allow_repeated_nodes`` (default ``False``) and ``n_repeat_trials``
  (default ``0``).
- ``max_trials_per_block``.

Blocks are set on the nodes. The ``demos/experiments/static`` demo puts each
animal in three blocks:

.. literalinclude:: ../../demos/experiments/static/experiment.py
   :start-at: nodes = [
   :end-before: class AnimalTrial

and limits each block to two trials, with three repeat trials at the end:

.. literalinclude:: ../../demos/experiments/static/experiment.py
   :start-at: trial_maker = AnimalTrialMaker(
   :end-before: class Exp

Participant groups are also set on the nodes:

.. code-block:: python

    StaticNode(definition={"instrument": "trumpet"}, participant_group="brass_players")

To assign participant groups, pass ``choose_participant_group``, a function
from the participant to a group name. It is required whenever nodes have
participant groups:

.. code-block:: python

    StaticTrialMaker(
        ...,
        choose_participant_group=lambda participant: participant.var.instrument_family,
    )

To let the trial maker decide when recruitment stops, pass
``recruit_mode="n_participants"`` with ``target_n_participants``, or
``recruit_mode="n_trials"`` with ``target_trials_per_node``.

.. _custom_node_selection:

To choose the node yourself, for example in an adaptive design, override two
hooks. :meth:`~psynet.trial.static.StaticTrialMaker.custom_node_filter`
removes nodes the participant must not receive, and
:meth:`~psynet.trial.static.StaticTrialMaker.select_node` picks one of the
rest; blocks, repeat rules, performance checks and trial-based recruitment
keep working. The nodes arrive in selection order (see
:ref:`trial_selection_performance`), and the default ``select_node`` takes
the first. ``select_node`` must return one of the objects it was given, not a
re-queried copy, either directly or wrapped in a
:class:`~psynet.trial.main.Selection` with a ``context``. Returning ``None``
raises ``TypeError``. PsyNet passes the context to
:meth:`~psynet.trial.main.NetworkTrialMaker.on_trial_created` as
``selection_context``:

.. code-block:: python

    class AdaptiveTrialMaker(StaticTrialMaker):
        def select_node(self, nodes, participant, experiment):
            scores = [score_item(node.definition) for node in nodes]
            best = max(range(len(nodes)), key=scores.__getitem__)
            return Selection(value=nodes[best], context={"score": scores[best]})

        def on_trial_created(self, trial, experiment, participant, selection_context=None):
            record = SelectionRecord(participant_id=participant.id, details=selection_context)
            record.trial = trial
            db.session.add(record)

``on_trial_created`` runs in the same database transaction as trial creation,
once per selection, for primary trials only: not for repeat trials or for the
copies given to other members of a synchronized group. Chain trial makers have
the equivalent hooks for chains; see :doc:`/code/writing_a_chain_experiment`.

.. _trial_order:

Trial order
~~~~~~~~~~~

A participant works through their blocks one at a time, and PsyNet only
considers nodes in the current block. The block ends when the participant
reaches ``max_trials_per_block``, when
:meth:`~psynet.trial.chain.ChainTrialMaker.should_finish_block` returns
``True``, or when the block has nothing more to give them. PsyNet then moves
to the next block, or leaves the trial maker after the last one.

``block_order`` sets the order of the blocks:

- ``"random"`` (default): a new random order for each participant.
- ``"listed"``: the order in which the blocks first appear in ``nodes``.
- A list of block names, used for every participant.
- A function that takes any of ``participant``, ``experiment`` and
  ``blocks`` and returns a list of block names. It may leave blocks out to
  give a participant only some of them.

``node_order`` sets the order of the nodes within a block. Dynamic orders
are recomputed in the database for each trial:

- ``"balanced"`` (default): nodes with the fewest trials first, ties broken
  at random.
- ``"random"``: a fresh random draw for each trial. Without
  ``allow_repeated_nodes`` this gives each participant the block's nodes in
  a random order; with it, a node can come up again before others have been
  seen. For a shuffle without such repeats, use a function such as
  ``lambda nodes: random.sample(nodes, len(nodes))``.

A custom :meth:`~psynet.trial.static.StaticTrialMaker.node_priority` sorts
first; a dynamic order only breaks ties among the nodes it ranks equally.

Planned orders are fixed when the participant enters the block:

- ``"listed"``: the order of ``nodes``.
- A function that takes any of ``participant``, ``experiment``, ``block``
  and ``nodes`` and returns the nodes in the order to present them.
  Returning fewer nodes gives the participant only those. With
  ``allow_repeated_nodes=True`` it may list a node more than once.

To use a different order in each block, pass a dict from block name to
order; it must name every block. For example, to counterbalance the block
order across participants and shuffle the conditions within each block with
at most two trials of the same condition in a row:

.. code-block:: python

    from psynet.utils import shuffle_with_max_run

    StaticTrialMaker(
        ...,
        block_order=lambda participant: ["A", "B"] if participant.id % 2 else ["B", "A"],
        node_order=lambda nodes: shuffle_with_max_run(
            nodes, key=lambda node: node.definition["condition"], max_run=2
        ),
    )

If a planned node can no longer take a trial, for example because it
already has ``target_trials_per_node`` trials, PsyNet skips it and logs a
warning. If it is waiting for asynchronous processing, the participant waits
for it. A planned order already decides which node comes next, so it cannot
be combined with ``select_node``, ``node_priority`` or ``find_nodes``; filter
with ``filter_nodes_query`` or ``custom_node_filter`` instead. Repeat trials
come after the last block and are not part of the plan.

Chain trial makers take ``block_order`` too, and ``chain_order`` in place of
``node_order``; see :doc:`/code/writing_a_chain_experiment`.

.. _trial_selection_performance:

Keeping selection fast
~~~~~~~~~~~~~~~~~~~~~~

PsyNet finds each trial's node with one database query. It orders the
eligible nodes by any custom priority, then by balancing (with
``node_order="balanced"``), then randomly, and loads only the first. It then
locks that node and recounts its trials, a small fixed cost that stops
simultaneous participants from overfilling it. Nodes are not eligible if they
already have ``target_trials_per_node`` trials, if they are waiting for
asynchronous processing, or if they are outside the participant's group or
current block. Planned orders (see :ref:`trial_order`) load the block's nodes
once, when the participant enters the block.

``custom_node_filter``, ``select_node`` and ``find_nodes`` run in Python, so
overriding them makes PsyNet load every eligible node for every trial. With a
few hundred nodes that is fine. With thousands it slows each response, and
PsyNet logs a warning. There are three ways to keep it fast:

- Filter and rank in the database.
  :meth:`~psynet.trial.static.StaticTrialMaker.filter_nodes_query` receives
  the query and returns it with extra conditions.
  :meth:`~psynet.trial.static.StaticTrialMaker.node_priority` returns SQL
  expressions to sort by. Both can use columns of ``self.node_class`` and
  ``self.network_class``, including columns you add to your own node class.
- Decide whether the participant should get a trial at all in
  :meth:`~psynet.trial.chain.ChainTrialMaker.before_selection`. It runs before
  PsyNet looks for nodes and returns ``"wait"``, ``"exit"`` or ``None`` (go
  ahead).
- Set ``selection_pool_size`` to pass only the best-ranked eligible nodes to
  the Python hooks. Nodes outside the pool are ignored for that trial.

.. code-block:: python

    class ColorTrialMaker(StaticTrialMaker):
        selection_pool_size = 50

        def filter_nodes_query(self, query, participant, experiment):
            # Hypothetical column added to the node class.
            return query.filter(self.node_class.difficulty <= participant.var.level)

        def node_priority(self, participant, experiment):
            return [self.node_class.difficulty.desc()]

        def select_node(self, nodes, participant, experiment):
            return max(nodes, key=lambda node: score_item(node.definition))

``filter_nodes_query`` and ``node_priority`` work in SQL, so they cannot read
``node.definition``, which PsyNet stores in encoded form. Store anything you
filter or rank on in its own column. Chain trial makers have the same
hooks under the names ``filter_chains_query`` and ``chain_priority``.

.. _trial_after_the_response:

After the response
------------------

:meth:`~psynet.trial.main.Trial.score_answer` returns the trial's score, which
is stored as ``self.score``. From ``demos/experiments/static``:

.. literalinclude:: ../../demos/experiments/static/experiment.py
   :pyobject: AnimalTrial.score_answer

:meth:`~psynet.trial.main.Trial.show_feedback` returns a page shown after the
response:

.. code-block:: python

    def show_feedback(self, experiment, participant):
        return InfoPage("Correct!" if self.score else "Incorrect.", time_estimate=3)

For recordings, return a page with an
:class:`~psynet.modular_page.AudioRecordControl` or
:class:`~psynet.modular_page.VideoRecordControl`. To analyze the recording on
the server, inherit from :class:`~psynet.trial.audio.AudioRecordTrial` (or
:class:`~psynet.trial.video.CameraRecordTrial`) *before* the trial class, and
define ``analyze_recording``. With the classes the other way round, the
analysis never runs. The returned dictionary must include ``"failed"``;
``True`` fails the trial. The ``demos/pipelines/tapping`` demo analyzes each
tapping recording:

.. literalinclude:: ../../demos/pipelines/tapping/repp_utils.py
   :pyobject: TapTrial.analyze_recording

The analysis runs in a background process. Feedback waits for it by default;
set ``wait_for_feedback = False`` on the trial class to skip waiting.

For a performance check, set ``check_performance_at_end=True`` or
``check_performance_every_trial=True`` and choose a built-in check with
``performance_check_type`` (``"score"``, ``"performance"``, or
``"consistency"``) and ``performance_threshold``. With ``score_answer``
defined, this passes participants whose total score is at least 5:

.. code-block:: python

    class CustomTrialMaker(StaticTrialMaker):
        performance_check_type = "score"
        performance_threshold = 5

    CustomTrialMaker(..., check_performance_at_end=True)

PsyNet raises an error if checks are enabled without a
``performance_check_type`` or a custom check. For other rules, override
:meth:`~psynet.trial.main.NetworkTrialMaker.performance_check` and return a
dictionary with ``score`` and ``passed``. To show a page to participants who
pass, set ``give_end_feedback_passed = True`` and override
:meth:`~psynet.trial.main.TrialMaker.get_end_feedback_passed_page`. The
``demos/experiments/static`` demo does both:

.. literalinclude:: ../../demos/experiments/static/experiment.py
   :pyobject: AnimalTrialMaker

To change what failing participants see, override
:meth:`~psynet.trial.main.TrialMaker.check_fail_logic`.

``fail_trials_on_participant_performance_check`` (default ``True``) controls
whether a failed check also fails the participant's trials in this trial
maker. See :doc:`/code/trials/participant_and_trial_failure`.

Trials without a trial maker
----------------------------

:meth:`~psynet.trial.main.Trial.cue` puts a single trial into the timeline,
with no trial maker. You then choose the trials yourself with timeline
constructs such as :func:`~psynet.timeline.for_loop`. The argument is either
the trial's definition or a node. In ``demos/experiments/trial``, each
participant rates three randomly sampled words:

.. literalinclude:: ../../demos/experiments/trial/experiment.py
   :start-at: word_ratings = Module(
   :end-before: class Exp

With a node, the trial takes the node's definition and can use its assets
through ``self.node.assets``. Pass the nodes to the enclosing
:class:`~psynet.timeline.Module`; functions inside the module can then take a
``nodes`` argument. From ``demos/experiments/trial_2``:

.. literalinclude:: ../../demos/experiments/trial_2/experiment.py
   :start-at: NODES = [
   :end-before: class Exp

Without nodes, pass trial-specific assets to ``cue`` with ``assets``. This
suits externally hosted and on-demand assets, as in
``demos/experiments/trial_3``:

.. literalinclude:: ../../demos/experiments/trial_3/experiment.py
   :start-at: audio_ratings = Module(
   :end-before: class Exp

To create related database records in the same transaction as the trial, pass
an ``on_trial_created`` callback, and pass request-local values for it through
``creation_context``. Assign relationships in the callback rather than IDs,
because the trial's database ID may not exist until the transaction flushes.
If the callback raises an exception, the trial and the related records are
both rolled back. Passing ``creation_context`` without ``on_trial_created``
raises an error. ``demos/features/trial_cue_adaptive`` uses this for a
participant-level staircase inside a :func:`~psynet.timeline.while_loop`; the
:doc:`/skills/make-experiment-adaptive` skill describes the recommended
approach to adaptive designs.

A trial maker is the better choice when trials should be balanced across
nodes or participants, when chains develop across participants, or when you
need performance checks or trial-based recruitment.

Where the data goes
-------------------

Nodes and trials are database rows, so you can inspect them in the dashboard's
database view while the experiment runs, and query them in code:

.. code-block:: python

    StaticNode.query.filter_by(trial_maker_id="ratings").all()
    trial.node
    node.all_trials
    participant.all_trials

:func:`psynet.experiment.get_trial_maker` returns a trial maker by its
``id_``.

.. seealso::

   :doc:`/reference/api/trial/static` and :doc:`/reference/api/trial/main` in
   the API reference.
