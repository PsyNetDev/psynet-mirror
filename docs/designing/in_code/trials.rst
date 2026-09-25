Trials and trial makers in code
===============================

This page shows how the ideas in :doc:`/designing/trials` appear in
``experiment.py``, using the ``demos/pipelines/simple_rating`` demo, where
participants rate instrument sounds on two scales.

How it works
------------

Nodes are usually built in a ``get_nodes`` function. Here, one
:class:`~psynet.trial.static.StaticNode` is created per audio file in
``static/instrument_sounds``, and the file's URL is stored in the definition:

.. literalinclude:: ../../../demos/pipelines/simple_rating/experiment.py
   :pyobject: get_nodes

The trial is a subclass of :class:`~psynet.trial.static.StaticTrial`. It needs
a ``time_estimate`` in seconds and a ``show_trial`` method that returns the
page. The trial's definition is available as ``self.definition``:

.. literalinclude:: ../../../demos/pipelines/simple_rating/experiment.py
   :pyobject: CustomTrial

The :class:`~psynet.trial.static.StaticTrialMaker` goes in the timeline:

.. literalinclude:: ../../../demos/pipelines/simple_rating/experiment.py
   :pyobject: get_timeline

What the trial adds
-------------------

Override :meth:`~psynet.trial.main.Trial.finalize_definition`. It receives a
copy of the node's definition and returns the trial's definition:

.. code-block:: python

    class CustomTrial(StaticTrial):
        def finalize_definition(self, definition, experiment, participant):
            definition["volume"] = random.uniform(0.75, 1.25)
            return definition

The method runs once, when the trial is created, so this is the right place
for random draws. Variation that only changes how existing files are
presented, such as the order of response options, needs no new files.
Generating a new media file for each trial is an advanced case; see
:doc:`/guides/trials/assets`.

For dense paradigms, where each trial samples a stimulus from a continuous
space, :mod:`psynet.trial.dense` provides trial classes that do the sampling
for you, such as :class:`~psynet.trial.dense.SingleStimulusTrial`. The
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

Blocks and participant groups are set on the nodes:

.. code-block:: python

    StaticNode(definition={"instrument": "violin"}, block="strings")
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

After the response
------------------

:meth:`~psynet.trial.main.Trial.score_answer` scores the answer, and
:meth:`~psynet.trial.main.Trial.show_feedback` returns a page shown after the
response, which can use ``self.score``:

.. code-block:: python

    class CustomTrial(StaticTrial):
        def score_answer(self, answer, definition):
            return int(answer == definition["correct_answer"])

        def show_feedback(self, experiment, participant):
            return InfoPage("Correct!" if self.score else "Incorrect.", time_estimate=3)

For recordings, return a page with an
:class:`~psynet.modular_page.AudioRecordControl` or
:class:`~psynet.modular_page.VideoRecordControl`. To analyze the recording on
the server, inherit from :class:`~psynet.trial.audio.AudioRecordTrial` (or
:class:`~psynet.trial.video.CameraRecordTrial`) *before* the trial class, and
define ``analyze_recording``. With the classes the other way round, the
analysis never runs. The returned dictionary must include ``"failed"``;
``True`` fails the trial.

.. code-block:: python

    class SingingTrial(AudioRecordTrial, StaticTrial):
        def analyze_recording(self, audio_file: str, output_plot: str):
            analysis = estimate_pitch(audio_file)
            plot_pitch(analysis, output_plot)
            return {**analysis, "failed": not analysis["voiced"]}

The analysis runs in a background process. Feedback waits for it by default;
set ``wait_for_feedback = False`` on the trial class to skip waiting. The
``TapTrial`` class in ``demos/pipelines/tapping/repp_utils.py`` is a complete
example.

For a performance check, choose a built-in check with
``performance_check_type`` (``"score"``, ``"performance"``, or
``"consistency"``) and set ``performance_threshold``. With ``score_answer``
defined, this passes participants whose total score is at least 5:

.. code-block:: python

    class CustomTrialMaker(StaticTrialMaker):
        performance_check_type = "score"
        performance_threshold = 5

    CustomTrialMaker(..., check_performance_at_end=True)

Use ``check_performance_every_trial=True`` to check after each trial instead.
PsyNet raises an error if checks are enabled without a
``performance_check_type`` or a custom check. For other rules, override
:meth:`~psynet.trial.main.NetworkTrialMaker.performance_check` and return a
dictionary with ``score`` and ``passed``. To change what failing participants
see, override :meth:`~psynet.trial.main.TrialMaker.check_fail_logic`. To show
a page to participants who pass, set ``give_end_feedback_passed = True`` and
override :meth:`~psynet.trial.main.TrialMaker.get_end_feedback_passed_page`.

``fail_trials_on_participant_performance_check`` (default ``True``) controls
whether a failed check also fails the participant's trials.

Where the data goes
-------------------

Nodes and trials are database rows, so you can inspect them in the dashboard's
database view while the experiment runs, and query them in code:

.. code-block:: python

    StaticNode.query.filter_by(trial_maker_id="ratings").all()
    trial.node
    node.all_trials
    participant.all_trials

:func:`~psynet.experiment.get_trial_maker` returns a trial maker by its
``id_``.

.. seealso::

   :doc:`/reference/api/trial/static` and :doc:`/reference/api/trial/main` in
   the API reference.
