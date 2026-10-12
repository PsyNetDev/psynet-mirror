# Iterated tapping from memory, adapted from Jacoby & McDermott (2017)
import json
import warnings
from statistics import mean

import numpy as np
from markupsafe import Markup
from repp.config import ConfigUpdater, sms_tapping

with warnings.catch_warnings():
    # repp.extensions.iterated_tapping imports numpy.matlib (used by
    # randomize_ioi_from_simplex). numpy.matlib emits a
    # PendingDeprecationWarning at import time, which PsyNet's pytest
    # setup escalates to an error.
    warnings.filterwarnings(
        "ignore",
        message=r"Importing from numpy\.matlib is deprecated.*",
        category=PendingDeprecationWarning,
    )
    from repp.extensions.iterated_tapping import (
        REPPAnalysisItapMemory,
        REPPStimulusItapMemory,
    )

from scipy.io import wavfile

import psynet.experiment
from psynet.asset import LocalStorage, S3Storage  # noqa
from psynet.modular_page import AudioPrompt, AudioRecordControl, ModularPage
from psynet.page import InfoPage
from psynet.prescreen import NumpySerializer, REPPTappingCalibration
from psynet.timeline import Event, ProgressDisplay, ProgressStage, Timeline
from psynet.trial.audio import (
    AudioImitationChainNode,
    AudioImitationChainTrial,
    AudioImitationChainTrialMaker,
)
from psynet.utils import get_logger

logger = get_logger()


# Global parameters
config = ConfigUpdater.create_config(
    sms_tapping,
    {
        "LABEL": "iterated tapping from memory (2-interval)",
        "USE_CLICK_FILENAME": True,
        "ONSET_MATCHING_WINDOW": 200.0,
        "CLEAN_NORMALIZE_FACTOR": 0.1,
        "PLOTS_TO_DISPLAY": [2, 2],
        "STIM_RANGE": [30, 800],
        "STIM_AMPLITUDE": 0.15,
        "INTERVAL_RHYTHM": 2,
        "REPEATS": 3,
        "MIN_RATIO": 1.0 / 10.0,
        "SLACK_RATIO": 0.95,
        "DURATION_RANGE": [250, 2000],
        "TOTAL_DURATION": 1000,
        "PROB_NO_CHANGE": 1 / 3,
        "MAX_DIFF_RATIO": 0.25,
        "MAX_DIF_IOI": 500,
        "IS_FIXED_DURATION": False,
        "MIN_TAPS_PLAYED": 5,
        "EXTRACT_SECOND_WINDOW": [26, 60],
        "SAMPLE_LOG_SCALE": True,
    },
)

stimulus = REPPStimulusItapMemory("itap_memory", config=config)
analysis_itap = REPPAnalysisItapMemory(config=config)

TIME_ESTIMATE_PER_TRIAL = config.REPEATS * 3

# failing criteria
MIN_RESPONSES_PLAYED = config.MIN_TAPS_PLAYED
# within chains
CHAINS_PER_PARTICIPANT = 2  # set to 4 for a real experiment
NUM_ITERATION_CHAIN = 2  # set to 5 for a real experiment
NUM_TRIALS_PARTICIPANT = 4  # set to 20 for a real experiment
TOTAL_NUM_PARTICIPANTS = 50


# Experiment parts
def save_samples_to_file(samples, filename, fs):
    wavfile.write(filename, rate=fs, data=samples.astype(np.float32))


def as_native_type(x):
    if type(x).__module__ == np.__name__:
        return x.item()
    return x


class CustomTrialAnalysis(AudioImitationChainTrial):
    def analyze_recording(self, audio_file: str, output_plot: str):
        info_stimulus = self.origin.var.info_stimulus
        title_in_graph = "Participant {}".format(self.participant_id)
        _, output_iteration = analysis_itap.do_analysis(
            info_stimulus["random_seed"], audio_file, title_in_graph, output_plot
        )
        new_seed = output_iteration["new_ioi_seed"]
        old_seed = output_iteration["old_ioi_seed"]
        failed = output_iteration["seed_needs_change"]
        reason = output_iteration["seed_needs_change_reason"]
        ratios_reps = output_iteration["resp_onsets_complete"]
        ratios_reps = json.dumps(ratios_reps, cls=NumpySerializer)
        output_iteration = json.dumps(output_iteration, cls=NumpySerializer)
        ioi_new_seed = [as_native_type(value) for value in new_seed]
        ioi_old_seed = [as_native_type(value) for value in old_seed]
        return {
            "failed": failed,
            "reason": reason,
            "ioi_new_seed": ioi_new_seed,
            "ioi_old_seed": ioi_old_seed,
            "ratios_reps": ratios_reps,
            "output_iteration": output_iteration,
        }


class CustomTrial(CustomTrialAnalysis):
    time_estimate = TIME_ESTIMATE_PER_TRIAL

    def show_trial(self, experiment, participant):
        info_stimulus = self.node.var.info_stimulus
        duration_rec_sec = info_stimulus["duration_rec_sec"]
        trial_number = self.position + 1
        n_trials = self.trial_maker.expected_trials_per_participant
        return ModularPage(
            "tapping_page",
            AudioPrompt(
                self.assets["stimulus"],
                Markup(
                    f"""
                    <h3>Imitate the rhythm</h3>
                    Listen to the rhythm and imitate it as best as you can by tapping with your finger.
                    <br><br>
                    <i>Trial number {trial_number} out of {n_trials} trials.</i>
                    """
                ),
            ),
            AudioRecordControl(
                duration=duration_rec_sec + 5,
                show_meter=False,
                controls=False,
                auto_advance=False,
                bot_response_media="example_tapping_memory_recording.wav",
            ),
            time_estimate=duration_rec_sec + 5,
            events={
                "promptStart": Event(is_triggered_by="trialStart", delay=0.5),
                "recordStart": Event(is_triggered_by="promptEnd", delay=0.5),
            },
            progress_display=ProgressDisplay(
                # show_bar=False,
                stages=[
                    ProgressStage(
                        (duration_rec_sec + 1),
                        "Listen to the rhythm and wait...",
                        "orange",
                    ),
                    ProgressStage(
                        [(duration_rec_sec + 1), (duration_rec_sec * 2 + 3)],
                        "START TAPPING!",
                        "red",
                    ),
                    ProgressStage(
                        1,
                        "Finished recording.",
                        "green",
                        persistent=False,
                    ),
                    ProgressStage(
                        0.5,
                        "Press Next when you are ready to continue...",
                        "orange",
                        persistent=True,
                    ),
                ],
            ),
        )


class CustomNode(AudioImitationChainNode):
    def summarize_trials(self, trials: list, experiment, participant):
        new_rhythm = [trial.analysis["ioi_new_seed"] for trial in trials]
        return [mean(x) for x in zip(*new_rhythm)]

    def synthesize_target(self, output_file):
        random_seed = self.definition
        stim, _, _ = stimulus.make_stim_from_seed(random_seed, repeats=config.REPEATS)
        self.var.info_stimulus = {
            "duration_rec_sec": len(stim) / config.FS,
            "random_seed": random_seed,
        }
        save_samples_to_file(stim, output_file, config.FS)

    def create_initial_seed(self, experiment, participant):
        config.DURATION_RANGE = self.duration_range
        ioi_seed = stimulus.make_ioi_seed(config.IS_FIXED_DURATION)
        random_seed = [as_native_type(value) for value in ioi_seed]
        return random_seed

    @property
    def duration_range(self):
        raise NotImplementedError


class PracticeNode(CustomNode):
    @property
    def duration_range(self):
        return [500, 2000]


class ExperimentNode(CustomNode):
    @property
    def duration_range(self):
        return [250, 2000]


# Timeline
class Exp(psynet.experiment.Experiment):
    label = "Tapping memory demo"

    # asset_storage = S3Storage("psynet-tests", "iterated-tapping")

    timeline = Timeline(
        REPPTappingCalibration(),  # calibrate tapping
        InfoPage(
            Markup(
                f"""
            <h3>Instructions</h3>
            <hr>
            You will take {NUM_TRIALS_PARTICIPANT} trials. In each trial, you will hear a metronome sound
            playing a rhythm.
            <br><br>
            <b><b>Your goal is to reproduce back the rhythm by tapping on the surface of your laptop</b></b>
            <br><br>
            Please make sure to reproduce the rhythm as accurately as possible.</li>
            <hr>
            Click <b>next</b> to start tapping in rhythm!
            """
            ),
            time_estimate=5,
        ),
        AudioImitationChainTrialMaker(
            id_="trial_maker_iterated_tapping",
            trial_class=CustomTrial,
            node_class=ExperimentNode,
            chain_type="within",
            expected_trials_per_participant=NUM_TRIALS_PARTICIPANT,
            max_nodes_per_chain=NUM_ITERATION_CHAIN,  # only relevant in within chains
            chains_per_participant=CHAINS_PER_PARTICIPANT,  # set to None if chain_type="across"
            chains_per_experiment=None,  # set to None if chain_type="within"
            trials_per_node=1,
            check_performance_at_end=False,
            check_performance_every_trial=False,
            propagate_failure=False,
            recruit_mode="n_participants",
            target_n_participants=TOTAL_NUM_PARTICIPANTS,
        ),
    )
