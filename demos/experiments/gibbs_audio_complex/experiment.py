import random

from markupsafe import Markup

import psynet.experiment
import psynet.media
from psynet.bot import Bot
from psynet.consent import LabRecruiterAudiovisualConsent, LabRecruiterStandardConsent
from psynet.timeline import Timeline
from psynet.trial.audio_gibbs import (
    AudioGibbsNode,
    AudioGibbsTrial,
    AudioGibbsTrialMaker,
)
from psynet.utils import get_logger

from . import custom_synth

logger = get_logger()

# Custom parameters, change these as you like!
TARGETS = ["sad", "happy", "angry"]
SENTENCE_RECORDINGS = [
    "Harvard_L35_S01_0.wav",
    "Harvard_L35_S02_0.wav",
    "Harvard_L35_S03_0.wav",
]
RANGES = [
    # DURATION
    # 1. Duration, percent
    [0.8, 1.2],
    # INTENSITY
    # 2. Tremolo rate, st
    [0.01, 5],
    # 3. Tremolo depth, dB
    [0.01, 10],
    # PITCH
    # 4. Shift, semitones
    [-3, 3],
    # 5. Range, percent
    [0.2, 1.8],
    # 6. Increase/Decrease, semitones
    [-3, 3],
    # 7. Jitter, custom unit
    [0, 10],
]
INITIAL_VALUES = [
    1,  # 1. Duration, percent
    0.1,  # 2. Tremolo rate, st
    0.05,  # 3. Tremolo depth, dB
    0,  # 4. Shift, semitones
    1,  # 5. Range, percent
    0,  # 6. Increase/Decrease, semitones
    0,  # 7. Jitter, custom unit
]
DIMENSIONS = len(INITIAL_VALUES)
MIN_DURATION = 5
TIME_ESTIMATE_PER_TRIAL = 5
GRANULARITY = 25
SNAP_SLIDER = False
AUTOPLAY = True
DEBUG = False

NUM_ITERATIONS_PER_CHAIN = DIMENSIONS * 2  # every dimension is visited twice
CHAINS_PER_EXPERIMENT = (
    len(TARGETS) * 3
)  # for each emotion there are 3 chains (each with a different sentence)
NUM_TRIALS_PER_PARTICIPANT = len(TARGETS) * 3  # every participant does 9 trials


class CustomTrial(AudioGibbsTrial):
    snap_slider = SNAP_SLIDER
    autoplay = AUTOPLAY
    debug = DEBUG
    minimal_time = MIN_DURATION
    time_estimate = TIME_ESTIMATE_PER_TRIAL

    def get_prompt(self, experiment, participant):
        return Markup(
            "Adjust the slider to make the speaker sound like she is "
            f"<strong>{self.context['target']}</strong>."
        )


class CustomNode(AudioGibbsNode):
    vector_length = DIMENSIONS
    vector_ranges = RANGES
    granularity = GRANULARITY

    n_jobs = 8  # <--- Parallelizes stimulus synthesis into 8 parallel processes at each worker node

    def create_initial_seed(self, experiment, participant):
        return {
            "vector": INITIAL_VALUES,  # Start at predefined zero points, i.e. not at a random point in space
            "initial_index": random.randint(0, self.vector_length - 1),  #
        }

    def synth_function(self, vector, output_path, chain_definition):
        custom_synth.synth_stimulus(vector, output_path, self.context["input_file"])


class CustomTrialMaker(AudioGibbsTrialMaker):
    response_timeout_sec = 1e9


trial_maker = CustomTrialMaker(
    id_="gibbs_audio_complex_demo",
    trial_class=CustomTrial,
    node_class=CustomNode,
    start_nodes=lambda: [
        CustomNode(context={"target": target, "input_file": sentence})
        for target in TARGETS
        for sentence in SENTENCE_RECORDINGS
    ],
    chain_type="across",  # can be "within" or "across"
    expected_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_nodes_per_chain=NUM_ITERATIONS_PER_CHAIN,
    trials_per_node=1,
    balance_across_chains=True,
    check_performance_at_end=False,
    check_performance_every_trial=False,
    propagate_failure=False,
    recruit_mode="n_trials",
    target_n_participants=None,
    wait_for_networks=True,
)


class Exp(psynet.experiment.Experiment):
    label = "Complex audio Gibbs sampling demo"

    timeline = Timeline(
        LabRecruiterStandardConsent(),
        LabRecruiterAudiovisualConsent(),
        trial_maker,
    )

    test_n_bots = 2

    def test_check_bot(self, bot: Bot, **kwargs):
        assert not bot.failed
        assert len(bot.alive_trials) == NUM_TRIALS_PER_PARTICIPANT
