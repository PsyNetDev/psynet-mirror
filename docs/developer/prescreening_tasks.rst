.. _developer:
.. highlight:: shell

.. _Creating pre-screening tasks:

============================
Creating pre-screening tasks
============================

.. warning::

    This tutorial needs updating to PsyNet v10

Have a look at the below examples and add a new class specifying your new pre-screening task in the file ``psynet/prescreen.py``.

A simple pre-screening task
^^^^^^^^^^^^^^^^^^^^^^^^^^^

In general, a pre-screening task is a :class:`~psynet.trial.Module` which contains some conditional logic for determining the participant's suitability for an experiment.

In the following we show an example of a pre-screening task that consists of a single Yes/No question checking for the participant's suitability for a follow-up hearing test.

The ``HearingImpairmentCheck`` class inherits from :class:`~psynet.trial.Module` and defines the actual pre-screening. It has a single event (:class:`~psynet.trial.Module`) assigned to its ``events`` property which consists of a ``label``, a :class:`~psynet.timeline.Page` (:class:`~psynet.modular_page.ModularPage`) for the participant's input and the logic (:class:`~psynet.timeline.conditional`) to determine a positive or negative outcome. In the negative case the :class:`~psynet.page.UnsuccessfulEndPage` is shown and the participant exits the pre-screening. This class also needs to be provided with a value for ``label``.

::

    import psynet.experiment
    from psynet.modular_page import ModularPage, PushButtonControl
    from psynet.page import InfoPage, Prompt, SuccessfulEndPage, UnsuccessfulEndPage
    from psynet.timeline import Module, Timeline, conditional, join

    class HearingImpairmentCheck(Module):
        def __init__(
                self,
                label = "hearing_impairment_check",
                time_estimate_per_trial: float = 3.0,
            ):
            self.label = label
            self.elts = join(
                ModularPage(
                    self.label,
                    Prompt("Do you have any kind of hearing impairment? (I.e., do you have any problems with your hearing?)"),
                    control=PushButtonControl(["Yes", "No"]),
                    time_estimate=time_estimate_per_trial,
                ),
                conditional(
                    "hearing_impairment_check",
                    lambda experiment, participant: participant.answer == "Yes",
                    UnsuccessfulEndPage(failure_tags=["performance_check", "hearing_impairment_check"])
                )
            )
            super().__init__(self.label, self.elts)

\* Another simple example would be a :class:`~psynet.modular_page.ModularPage` with a :class:`~psynet.modular_page.TextControl` where the text provided by the participant is evaluated by some logic determining the positive/negative outcome.

A pre-screening task can then be included in an experiment as follows:

::

    import psynet.experiment
    from psynet.page import InfoPage, SuccessfulEndPage
    from psynet.timeline import Timeline
    # code for importing HearingImpairmentCheck

    class Exp(psynet.experiment.Experiment):
        timeline = Timeline(
            HearingImpairmentCheck(),
            InfoPage("Congratulations! You have no hearing impairment.", time_estimate=3),
            SuccessfulEndPage()
        )


For more advanced examples, please refer to the source code of the three static pre-screening tasks :class:`~psynet.prescreen.ColorVocabularyTest`, :class:`~psynet.prescreen.ColorVocabularyTest`, and :class:`~psynet.prescreen.HugginsHeadphoneTest` presented above or continue to the next section where we provide some boilerplate code for building static pre-screening tasks.

Static pre-screening tasks (Boilerplate code)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In this section we provide code snippets for building static pre-screening tasks utilizing :class:`~psynet.trial.main.TrialMaker` and :class:`~psynet.trial.static.StimulusSet`.

A static pre-screening task inherits from :class:`~psynet.trial.Module`, e.g.:

::

    from psynet.timeline import Module, join

    class SomeStaticPrescreeningTask(Module):
        def __init__(
            self,
            label = "some_static_prescreening_task",
            performance_threshold: int = 4,
        ):
        self.label = label
        self.elts = join(
            self.instruction_page(),
            self.trial_maker(performance_threshold)
        )
        super().__init__(self.label, self.elts)


Set reasonable defaults for ``performance_threshold`` and ``label``. Implement the four methods :meth:`instruction_page`, :meth:`trial_maker`, :meth:`trial`, and :meth:`get_stimulus_set`.
The :meth:`instruction_page` method returns an :class:`~psynet.page.InfoPage`, e.g.:

::

    from markupsafe import Markup
    from psynet.page import InfoPage

    def instruction_page(self):
        return InfoPage(Markup(
            """
            <p>We will now perform a test to check your ability to ....</p>
            <p>
                Text for explaining the procedure in more detail.
            </p>
            """
        ), time_estimate=10)


The :meth:`trial_maker` method returns a :class:`~psynet.trial.main.TrialMaker` overriding :meth:`~psynet.trial.main.performance_check`, e.g.:

::

    from psynet.trial.static import StaticTrialMaker

    def trial_maker(
            self,
            performance_threshold: int
        ):
        class SomeStaticPrescreeningTrialMaker(StaticTrialMaker):
            def performance_check(self, experiment, participant, participant_trials):
                # Calculate values for ``score`` and ``passed``
                return {
                    "score": score,
                    "passed": passed
                }

        return SomeStaticPrescreeningTrialMaker(
            id_="some_static_prescreening_trials",
            trial_class=self.trial(time_estimate_per_trial),
            phase="some_prescreening_phase",
            stimulus_set=self.get_stimulus_set(),
            check_performance_at_end=True,
            # Most shipped prescreens keep the static default (True).
            fail_trials_on_participant_performance_check=False,
        )

Premature exit never fails completed trials, so prescreens do not need a
special premature-exit setting. If the performance check only decides
whether the participant may continue, set
``fail_trials_on_participant_performance_check=False`` so the collected
trials remain valid measurements of ineligibility. Built-in prescreens keep
the static default (``True``) except ``FreeTappingRecordTest``, which sets
this to ``False``.

The :meth:`trial` method returns a :class:`~psynet.trial.static.StaticTrial` which implements :meth:`~psynet.trial.main.show_trial` that in turn returns a :class:`~psynet.modular_page.ModularPage` e.g.:

::

    from psynet.page import ModularPage
    from psynet.trial.static import StaticTrial

    def trial(self, time_estimate_: float):
        class SomeStaticPrescreeningTrial(StaticTrial):
            __mapper_args__ = {"polymorphic_identity": "some_prescreening_trial"}

            time_estimate = time_estimate_

            def show_trial(self, experiment, participant):
                return ModularPage(
                    "some_static_prescreening_trial",
                    # Define what is presented to the participant and how participants
                    # may respond utilizing the two principal ``ModularPage``
                    # components ``Prompt`` and ``Control``.
                    #
                    # Prompt(
                    #     "Choose between 1, 2, and 3!"
                    # ),
                    # PushButtonControl(
                    #     ["1", "2", "3"]
                    # ),
                    time_estimate=self.time_estimate
                )
        return SomeStaticPrescreeningTrial

The :meth:`get_stimulus_set` method returns a :class:`~psynet.trial.static.StimulusSet`,  e.g.:

::

    from psynet.trial.static import StimulusSet, StimulusSpec

    def get_stimulus_set(self):
        stimuli = []
        # Construct a list of ``StimulusSpec`` objects and pass it to
        # the ``StimulusSet`` constructor.
        return StimulusSet("some_prescreening_task", stimuli)

For concrete implementations, refer to the source code of the three static pre-screening tasks :class:`~psynet.prescreen.ColorVocabularyTest`, :class:`~psynet.prescreen.ColorVocabularyTest`, and :class:`~psynet.prescreen.HugginsHeadphoneTest`.
