from typing import List

from markupsafe import Markup

import psynet.experiment
import psynet.media
from psynet.bot import Bot
from psynet.consent import LabRecruiterStandardConsent
from psynet.page import InfoPage
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
TARGETS = ["dominant", "trustworthy"]
DIMENSIONS = 7
RANGE = [-800, 800]
GRANULARITY = 25
SNAP_SLIDER = True
AUTOPLAY = True
DEBUG = False
NUM_ITERATIONS_PER_CHAIN = (
    2  # In a real experiment we'd make this something like DIMENSIONS * 2
)
CHAINS_PER_PARTICIPANT = len(TARGETS)
NUM_TRIALS_PER_PARTICIPANT = NUM_ITERATIONS_PER_CHAIN * CHAINS_PER_PARTICIPANT


class CustomTrial(AudioGibbsTrial):
    snap_slider = SNAP_SLIDER
    autoplay = AUTOPLAY
    debug = DEBUG
    minimal_time = 3.0
    time_estimate = 5.0

    def get_prompt(self, experiment, participant):
        return Markup(
            "Adjust the slider so that the word sounds as "
            f"<strong>{self.context['target']}</strong> "
            "as possible."
        )


class CustomNode(AudioGibbsNode):
    vector_length = DIMENSIONS
    vector_ranges = [RANGE for _ in range(DIMENSIONS)]
    granularity = GRANULARITY
    n_jobs = 8  # <--- Parallelizes stimulus synthesis into 8 parallel processes at each worker node

    def synth_function(self, vector, output_path, chain_definition):
        custom_synth.synth_stimulus(vector, output_path, chain_definition)


class CustomTrialMaker(AudioGibbsTrialMaker):
    performance_threshold = -1.0
    give_end_feedback_passed = True

    def get_end_feedback_passed_page(self, score):
        score_to_display = "NA" if score is None else f"{(100 * score):.0f}"

        return InfoPage(
            Markup(
                f"Your consistency score was <strong>{score_to_display}&#37;</strong>."
            ),
            time_estimate=5,
        )


trial_maker = CustomTrialMaker(
    id_="gibbs_audio_demo",
    trial_class=CustomTrial,
    node_class=CustomNode,
    chain_type="within",  # can be "within" or "across"
    expected_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_nodes_per_chain=NUM_ITERATIONS_PER_CHAIN,
    start_nodes=lambda: [CustomNode(context={"target": target}) for target in TARGETS],
    chains_per_experiment=None,  # set to None if chain_type="within"
    trials_per_node=1,
    chain_order="balanced",
    check_performance_at_end=True,
    check_performance_every_trial=False,
    propagate_failure=False,
    recruit_mode="n_participants",
    target_n_participants=10,
    wait_for_networks=True,
)

##########################################################################################
# Experiment
##########################################################################################


class Exp(psynet.experiment.Experiment):
    label = "Audio Gibbs sampling demo"

    timeline = Timeline(
        LabRecruiterStandardConsent(),
        trial_maker,
    )

    test_n_bots = 2

    def test_bots_ran_successfully(self, bots: List[Bot], **kwargs):
        super().test_bots_ran_successfully(bots, **kwargs)

        for b in bots:
            assert len(b.alive_trials) == NUM_TRIALS_PER_PARTICIPANT
