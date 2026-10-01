import pytest

import psynet.experiment
from psynet.asset import CachedFunctionAsset, S3Storage
from psynet.bot import Bot
from psynet.modular_page import (
    AudioMeterControl,
    AudioPrompt,
    AudioRecordControl,
    ModularPage,
)
from psynet.page import InfoPage, VolumeCalibration
from psynet.timeline import Event, ProgressDisplay, ProgressStage, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

from .custom_synth import synth_prosody

##########################################################################################
# Stimuli
##########################################################################################


def synth_stimulus(path, frequencies):
    synth_prosody(vector=frequencies, output_path=path)


nodes = [
    StaticNode(
        definition={
            "frequency_gradient": frequency_gradient,
            "start_frequency": start_frequency,
            "frequencies": [start_frequency + i * frequency_gradient for i in range(5)],
        },
        assets={
            "stimulus": CachedFunctionAsset(
                function=synth_stimulus,
                extension=".wav",
            )
        },
    )
    for frequency_gradient in [-100, 0, 100]
    for start_frequency in [-100, 0, 100]
]


class CustomTrial(StaticTrial):
    _time_trial = 3
    _time_feedback = 2

    time_estimate = _time_trial + _time_feedback
    wait_for_feedback = True

    def show_trial(self, experiment, participant):
        stimulus_duration = 0.393
        record_duration = 2.0

        return ModularPage(
            "imitation",
            AudioPrompt(
                self.assets["stimulus"],
                "Please imitate the spoken word as closely as possible.",
            ),
            AudioRecordControl(
                duration=record_duration,
                bot_response_media="example-bier.wav",
                auto_advance=True,
            ),
            time_estimate=self._time_trial,
            start_trial_automatically=False,
            show_start_button=True,
            show_next_button=False,
            progress_display=ProgressDisplay(
                stages=[
                    ProgressStage([0.0, stimulus_duration], color="grey"),
                    ProgressStage(
                        [stimulus_duration, stimulus_duration + record_duration],
                        caption="Recording...",
                        color="red",
                    ),
                    ProgressStage(
                        [
                            stimulus_duration + record_duration,
                            stimulus_duration + record_duration + stimulus_duration,
                        ],
                        caption="Uploading, please wait...",
                        color="grey",
                    ),
                ],
            ),
            events={"recordStart": Event(is_triggered_by="promptEnd")},
        )

    def show_feedback(self, experiment, participant):
        return ModularPage(
            "feedback",
            AudioPrompt(
                self.assets["imitation"],
                "Listen back to your recording. Did you do a good job?",
            ),
            time_estimate=self._time_feedback,
        )


class Exp(psynet.experiment.Experiment):
    label = "Static audio demo"

    asset_storage = S3Storage("psynet-tests", "static-audio")

    timeline = Timeline(
        VolumeCalibration(),
        ModularPage(
            "record_calibrate",
            """
            Please speak into your microphone and check that the sound is registered
            properly. If the sound is too quiet, try moving your microphone
            closer or increasing the input volume on your computer.
            """,
            AudioMeterControl(),
            time_estimate=5,
        ),
        InfoPage(
            """
            In this experiment you will hear some words. Your task will be to repeat
            them back as accurately as possible.
            """,
            time_estimate=5,
        ),
        StaticTrialMaker(
            id_="static_audio",
            trial_class=CustomTrial,
            nodes=nodes,
            expected_trials_per_participant=len(nodes),
            target_n_participants=3,
            recruit_mode="n_participants",
        ),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        assert len(bot.alive_trials) == len(nodes)

        for trial in bot.alive_trials:
            assert trial.progress_before_trial < 1.0

            if trial.id < len(nodes):
                assert trial.progress_after_trial < 1.0
            else:
                assert trial.progress_after_trial == pytest.approx(1.0)

        # Timeline duration is an estimate; asynchronous asset waits credit the
        # participant's actual visible waiting time. Feedback holds use
        # expected_wait=0, so any visible wait is additional to the timeline
        # estimate. Bots often find the imitation asset already deposited and
        # skip the hold, so wait time may be zero.
        assert bot.time_credit == pytest.approx(
            self.estimated_completion_time(wage_per_hour=0.0) + bot.total_wait_page_time
        )
