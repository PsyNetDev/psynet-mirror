.. _developer:
.. highlight:: python

.. _Creating pre-screening tasks:

============================
Creating pre-screening tasks
============================

Put custom pre-screens in your experiment, not in the PsyNet package.
Ready-made tests for color blindness, color vocabulary, headphones, and
audio classification are listed in
:doc:`/guides/participants/prescreening_tasks`.

A simple pre-screen
^^^^^^^^^^^^^^^^^^^

A one-question pre-screen is a :class:`~psynet.timeline.Module` that
asks the participant something and uses
:func:`~psynet.timeline.conditional` to send failing participants to
:class:`~psynet.page.UnsuccessfulEndPage`.

::

    from psynet.modular_page import ModularPage, Prompt, PushButtonControl
    from psynet.page import InfoPage, SuccessfulEndPage, UnsuccessfulEndPage
    from psynet.timeline import Module, Timeline, conditional, join

    import psynet.experiment


    class HearingImpairmentCheck(Module):
        def __init__(
            self,
            label="hearing_impairment_check",
            time_estimate_per_trial: float = 3.0,
        ):
            self.label = label
            elts = join(
                ModularPage(
                    self.label,
                    Prompt(
                        "Do you have any kind of hearing impairment? "
                        "(I.e., do you have any problems with your hearing?)"
                    ),
                    control=PushButtonControl(["Yes", "No"]),
                    time_estimate=time_estimate_per_trial,
                ),
                conditional(
                    "hearing_impairment_check",
                    lambda experiment, participant: participant.answer == "Yes",
                    UnsuccessfulEndPage(
                        failure_tags=["performance_check", "hearing_impairment_check"]
                    ),
                ),
            )
            super().__init__(self.label, elts)


    class Exp(psynet.experiment.Experiment):
        timeline = Timeline(
            HearingImpairmentCheck(),
            InfoPage("Congratulations! You have no hearing impairment.", time_estimate=3),
            SuccessfulEndPage(),
        )

A ``ModularPage`` with a :class:`~psynet.modular_page.TextControl` works
the same way: evaluate the typed answer in the ``conditional``.

A static multi-trial pre-screen
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A multi-trial pre-screen is a
:class:`~psynet.trial.static.StaticTrialMaker` with
``check_performance_at_end=True``. Each trial implements
``score_answer``. With ``performance_check_type = "score"``, the
participant passes if the sum of trial scores meets
``performance_threshold``.

Define the items with :class:`~psynet.trial.static.StaticNode` (the
older ``StimulusSet`` / ``StimulusSpec`` API is gone). Built-in examples
are :class:`~psynet.prescreen.ColorBlindnessTest`,
:class:`~psynet.prescreen.ColorVocabularyTest`, and
:class:`~psynet.prescreen.HugginsHeadphoneTest`.

::

    from markupsafe import Markup

    from psynet.modular_page import ModularPage, Prompt, PushButtonControl
    from psynet.page import InfoPage
    from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


    class SomeStaticPrescreeningTrial(StaticTrial):
        __mapper_args__ = {"polymorphic_identity": "some_prescreening_trial"}

        time_estimate = 5.0

        def show_trial(self, experiment, participant):
            return ModularPage(
                "some_static_prescreening_trial",
                Prompt("Choose between 1, 2, and 3!"),
                PushButtonControl(["1", "2", "3"]),
                time_estimate=self.time_estimate,
            )

        def score_answer(self, answer, definition):
            return 1 if answer == definition["correct_answer"] else 0


    class SomeStaticPrescreeningTask(StaticTrialMaker):
        performance_check_type = "score"

        def __init__(
            self,
            label="some_static_prescreening_task",
            performance_threshold: int = 4,
        ):
            self.performance_threshold = performance_threshold
            nodes = [
                StaticNode(definition={"correct_answer": "2"}),
                # ... more items ...
            ]
            super().__init__(
                id_=label,
                trial_class=SomeStaticPrescreeningTrial,
                nodes=nodes,
                expected_trials_per_participant=len(nodes),
                check_performance_at_end=True,
            )

        @property
        def introduction(self):
            return InfoPage(
                Markup(
                    """
                    <p>We will now perform a test to check your ability to ....</p>
                    """
                ),
                time_estimate=10,
            )

If the performance check only decides whether the participant may
continue, set
``fail_trials_on_participant_performance_check=False`` so the collected
trials remain valid measurements of ineligibility. The static default is
``True``. Built-in prescreens keep that default except
``FreeTappingRecordTest``, which sets it to ``False``.
