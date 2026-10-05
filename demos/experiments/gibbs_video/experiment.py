import psynet.experiment
import psynet.media
from psynet.consent import LabRecruiterStandardConsent
from psynet.modular_page import Markup
from psynet.timeline import Timeline
from psynet.trial.media_gibbs import (
    VideoGibbsNode,
    VideoGibbsTrial,
    VideoGibbsTrialMaker,
)
from psynet.utils import get_logger

from . import custom_synth

logger = get_logger()

# Custom parameters, change these as you like!
TARGETS = ["positive", "energetic"]
DURATION_RANGE = [0.1, 1.5]
RGB_RANGE = [0, 255]
VECTOR_RANGES = [
    RGB_RANGE,
    RGB_RANGE,
    RGB_RANGE,
    RGB_RANGE,
    RGB_RANGE,
    RGB_RANGE,
    DURATION_RANGE,
    DURATION_RANGE,
]
DIMENSIONS = len(VECTOR_RANGES)
GRANULARITY = 25  # 25 different slider positions
SNAP_SLIDER = True
AUTOPLAY = True
DEBUG = False
NUM_ITERATIONS_PER_CHAIN = DIMENSIONS * 2

NUM_CHAINS_PER_EXPERIMENT = 2
NUM_CHAINS_PER_PARTICIPANT = 2
NUM_TRIALS_PER_PARTICIPANT = 2


class CustomTrial(VideoGibbsTrial):
    snap_slider = SNAP_SLIDER
    autoplay = AUTOPLAY
    debug = DEBUG
    minimal_interactions = 3
    minimal_time = 3.0
    time_estimate = 5.0
    disable_slider_on_change = "while_playing"
    media_width = "250px"
    media_height = "250px"
    layout = ["media", "prompt", "progress", "control", "buttons"]

    def get_prompt(self, experiment, participant):
        return Markup(
            "<center>Adjust the slider so that the video is as "
            f"<strong>{self.context['target']}</strong> "
            "as possible.</center></br></br>"
            "In each trial of this experiment, you use the slider to choose between different video clips. "
            "In this case, every video contains an alternation between two colored squares. Each of the squares is "
            "presented twice. How long each of the colored squares is presented also varies."
            "The slider is disabled as long as a video is playing. The next button is activated the earliest after "
            "three seconds and minimally three interactions with the slider are required.",
        )


class CustomNode(VideoGibbsNode):
    vector_length = DIMENSIONS
    vector_ranges = VECTOR_RANGES
    granularity = GRANULARITY
    n_jobs = 8  # <--- Parallelizes stimulus synthesis into 8 parallel processes at each worker node

    def synth_function(self, vector, output_path, chain_definition):
        custom_synth.synth_stimulus(vector, output_path, {})


class CustomTrialMaker(VideoGibbsTrialMaker):
    pass


trial_maker = CustomTrialMaker(
    id_="gibbs_video_demo",
    trial_class=CustomTrial,
    node_class=CustomNode,
    chain_type="across",  # can be "within" or "across"
    expected_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_nodes_per_chain=NUM_ITERATIONS_PER_CHAIN,
    start_nodes=lambda: [CustomNode(context={"target": target}) for target in TARGETS],
    chains_per_experiment=NUM_CHAINS_PER_EXPERIMENT,  # set to None if chain_type="within"
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
    label = "Video Gibbs sampling demo"

    timeline = Timeline(
        LabRecruiterStandardConsent(),
        trial_maker,
    )
