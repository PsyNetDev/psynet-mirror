from markupsafe import Markup

import psynet.experiment
import psynet.media
from psynet.timeline import Timeline
from psynet.trial.media_gibbs import HtmlGibbsNode, HtmlGibbsTrial, HtmlGibbsTrialMaker
from psynet.utils import get_logger

from . import custom_synth

logger = get_logger()

# Custom parameters, change these as you like!
TARGETS = ["positive", "energetic"]
RGB_RANGE = [0, 255]
VECTOR_RANGES = [RGB_RANGE, RGB_RANGE, RGB_RANGE]
DIMENSIONS = len(VECTOR_RANGES)
GRANULARITY = 25  # 25 different slider positions
SNAP_SLIDER = True
AUTOPLAY = True
DEBUG = False
NUM_ITERATIONS_PER_CHAIN = DIMENSIONS * 2

NUM_CHAINS_PER_EXPERIMENT = 2
NUM_CHAINS_PER_PARTICIPANT = 2
NUM_TRIALS_PER_PARTICIPANT = 2


class CustomTrial(HtmlGibbsTrial):
    snap_slider = SNAP_SLIDER
    autoplay = AUTOPLAY
    debug = DEBUG
    minimal_interactions = 1
    minimal_time = 12.0
    time_estimate = 5.0
    continuous_updates = False
    disable_slider_on_change = 5.0
    media_width = "250px"
    media_height = "250px"
    layout = ["media", "prompt", "progress", "control", "buttons"]

    def get_prompt(self, experiment, participant):
        return Markup(
            "<center>Adjust the slider so that the image is as "
            f"<strong>{self.context['target']}</strong> "
            "as possible.</center></br>"
            "In each trial of this experiment, you use the slider to choose between different dynamic SVG images. "
            "In this case, every SVG image contains a colored square changing into white and going back to its original color over a duration of five seconds."
            "The slider is disabled for five seconds when the slider value is changed. For the next button to be activated, twelve seconds need to be passed and minimally one interaction with the slider is required. "
        )


class CustomNode(HtmlGibbsNode):
    vector_length = DIMENSIONS
    vector_ranges = VECTOR_RANGES
    granularity = GRANULARITY
    n_jobs = 8  # <--- Parallelize stimulus synthesis into 8 parallel processes at each worker node

    def synth_function(self, vector, output_path, chain_definition):
        custom_synth.synth_stimulus(vector, output_path, {})


trial_maker = HtmlGibbsTrialMaker(
    id_="gibbs_svg_demo",
    trial_class=CustomTrial,
    node_class=CustomNode,
    chain_type="across",  # can be "within" or "across"
    expected_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_nodes_per_chain=NUM_ITERATIONS_PER_CHAIN,
    start_nodes=lambda: [CustomNode(context={"target": target}) for target in TARGETS],
    chains_per_experiment=NUM_CHAINS_PER_EXPERIMENT,  # set to None if chain_type="within"
    trials_per_node=1,
    chain_order="balanced",
    check_performance_at_end=False,
    check_performance_every_trial=False,
    propagate_failure=False,
    recruit_mode="n_trials",
    target_n_participants=None,
    wait_for_networks=True,
)


class Exp(psynet.experiment.Experiment):
    label = "SVG Gibbs sampling demo"

    timeline = Timeline(
        trial_maker,
    )
