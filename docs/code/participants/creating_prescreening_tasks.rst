============================
Creating pre-screening tasks
============================

Put custom pre-screening tasks in your experiment, not in the PsyNet package.

A single question
-----------------

A one-question pre-screening task is a :class:`~psynet.timeline.Module` that
asks the question and uses :func:`~psynet.timeline.conditional` to send
failing participants to :class:`~psynet.page.UnsuccessfulEndPage`:

.. code-block:: python

    from psynet.modular_page import ModularPage, PushButtonControl
    from psynet.page import UnsuccessfulEndPage
    from psynet.timeline import Module, conditional


    def hearing_impairment_check():
        return Module(
            "hearing_impairment_check",
            ModularPage(
                "hearing_impairment",
                "Do you have any kind of hearing impairment?",
                PushButtonControl(["Yes", "No"]),
                time_estimate=3,
            ),
            conditional(
                "fail_if_impaired",
                lambda participant: participant.answer == "Yes",
                UnsuccessfulEndPage(failure_tags=["hearing_impairment_check"]),
            ),
        )

Place ``hearing_impairment_check()`` in the timeline before the main task.
With a :class:`~psynet.modular_page.TextControl`, evaluate the typed answer
in the ``conditional`` in the same way.

Several scored trials
---------------------

A test with several trials is a
:class:`~psynet.trial.static.StaticTrialMaker` with
``check_performance_at_end=True``. Each trial implements
:meth:`~psynet.trial.main.Trial.score_answer`. With
``performance_check_type = "score"``, the participant passes if the sum of the
trial scores reaches ``performance_threshold``, and a participant who fails is
sent to an :class:`~psynet.page.UnsuccessfulEndPage`.

:class:`~psynet.prescreen.ColorBlindnessTest` is built this way. Its trial
shows an image and scores the typed number:

.. literalinclude:: ../../../psynet/prescreen/__init__.py
   :pyobject: ColorBlindnessTrial

The trial maker defines one :class:`~psynet.trial.static.StaticNode` per
image, and passes the threshold and trial count on to
:class:`~psynet.trial.static.StaticTrialMaker`:

.. literalinclude:: ../../../psynet/prescreen/__init__.py
   :pyobject: ColorBlindnessTest.get_nodes

.. literalinclude:: ../../../psynet/prescreen/__init__.py
   :pyobject: ColorBlindnessTest.__init__

The class also sets ``performance_check_type = "score"`` and defines an
``introduction`` property that returns the instructions page.

If the test only decides whether the participant may continue, set
``fail_trials_on_participant_performance_check=False`` so that the trials of
participants who fail stay valid. The default for static trial makers is
``True``.
