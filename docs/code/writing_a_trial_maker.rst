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
- ``balance_across_nodes`` (default ``True``).
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

To choose the block order, subclass the trial maker and override
:meth:`~psynet.trial.chain.ChainTrialMaker.choose_block_order`. To assign
participant groups, pass ``choose_participant_group``, a function from the
participant to a group name. It is required whenever nodes have participant
groups:

.. code-block:: python

    class CustomTrialMaker(StaticTrialMaker):
        def choose_block_order(self, experiment, participant, blocks):
            return sorted(blocks)

    CustomTrialMaker(
        ...,
        choose_participant_group=lambda participant: participant.var.instrument_family,
    )

To let the trial maker decide when recruitment stops, pass
``recruit_mode="n_participants"`` with ``target_n_participants``, or
``recruit_mode="n_trials"`` with ``target_trials_per_node``.

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
   :start-at: audio_ratings = Module(
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
``demos/features/trial_cue_adaptive`` uses this for a participant-level
staircase inside a :func:`~psynet.timeline.while_loop`:

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :pyobject: record_decision

.. literalinclude:: ../../demos/features/trial_cue_adaptive/experiment.py
   :pyobject: select_and_cue

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
