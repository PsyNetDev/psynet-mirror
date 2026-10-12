import psynet.experiment
from psynet.bot import Bot
from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
from psynet.page import InfoPage, VolumeCalibration
from psynet.prescreen import AudioForcedChoiceTest, AudioForcedChoiceTrial
from psynet.timeline import Timeline

QUESTION = "The user should read the sentence: '%s'. Please select the error category."


class ReadAudioForcedChoiceTrial(AudioForcedChoiceTrial):
    def show_trial(self, experiment, participant):
        return ModularPage(
            "read_audio_test_trial",
            AudioPrompt(
                self.definition["url"],
                QUESTION % self.definition["text"],
            ),
            PushButtonControl(self.definition["answer_options"]),
            bot_response=self.definition["answer"],
        )


class ReadAudioTest(AudioForcedChoiceTest):
    def __init__(
        self,
        csv_path: str,
        answer_options: list,
        instructions: str,
        performance_threshold: int,
        question="",
        label="read_audio_test",
        n_stimuli_to_use: int = None,
        specific_indexes: list = None,
    ):
        super().__init__(
            csv_path=csv_path,
            answer_options=answer_options,
            instructions=instructions,
            question=question,
            performance_threshold=performance_threshold,
            label=label,
            n_stimuli_to_use=n_stimuli_to_use,
            specific_stimuli=specific_indexes,
            trial_class=ReadAudioForcedChoiceTrial,
        )

    def check_stimuli(self, stimuli, specific_stimuli):
        super().check_stimuli(stimuli, specific_stimuli)
        assert all(["text" in stimulus for stimulus in stimuli])


##########################################################################################
# Experiment
##########################################################################################


class Exp(psynet.experiment.Experiment):
    label = "Audio forced choice demo"

    timeline = Timeline(
        VolumeCalibration(),
        AudioForcedChoiceTest(
            csv_path="cats_dogs_birds.csv",
            answer_options=["cat", "dog", "bird"],
            performance_threshold=1,
            instructions="""
                    <p>In each trial, you will hear a sound of an animal. Please select the correct animal category.</p>
                    """,
            question="Select the category which fits best to the played sound file.",
        ),
        ReadAudioTest(
            csv_path="test_set.csv",
            answer_options=[
                "Too much background noise",
                "Wrong sentence is read",
                "Repetition",
                "Recording is cut off",
                "Completely silent",
                "none",
            ],
            specific_indexes=[0, 19, 32, 43, 52, 70],
            performance_threshold=1,
            instructions="""
                        <p>In each trial, you will hear a recording of a sentence. The sentence that should be recorded
                        is printed during every trial.
                        Not all recordings are good. There are different kinds of errors:
                        1) a recording can contain too much background noise, 2) the sentence read by the participant
                        is different from the sentence printed at the top of the page. 3) the sentence is repeated, 4)
                        the recordings starts too late or ends too early, 5) the speaker does not say anything.

                        If none of the five errors apply, you should select the sixth button "None"</p>
                        """,
        ),
        InfoPage("You passed all screening tasks! Congratulations.", time_estimate=3),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        assert len(bot.alive_trials) == 3 + 6
        assert not bot.failed
