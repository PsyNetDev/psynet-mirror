# pylint: disable=unused-import,abstract-method,unused-argument,no-member
import numpy as np

import psynet.experiment
import psynet.media
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import MediaSpec, Timeline
from psynet.trial.audio_gibbs import (
    AudioGibbsNode,
    AudioGibbsTrial,
    AudioGibbsTrialMaker,
)
from psynet.trial.create_and_rate import (
    CreateAndRateNodeMixin,
    CreateAndRateTrialMakerMixin,
    CreateTrialMixin,
    RateTrialMixin,
    SelectTrialMixin,
)
from psynet.trial.imitation_chain import ImitationChainTrial
from psynet.utils import get_logger

from . import custom_synth
from .utils import (
    find_nearest,
    get_prompt,
    get_target_gibbs_answer,
    main_experiment_urls,
    prepare_audio_events,
)

# Note: parselmouth must be installed with pip install praat-parselmouth

##########################################################################################
# Imports
##########################################################################################


logger = get_logger()

# Custom parameters, change these as you like!
DIMENSIONS = 7
RANGE = [-800, 800]
GRANULARITY = 25
SNAP_SLIDER = True
AUTOPLAY = True
DEBUG = False
AUDIO_DURATION = 0.75

RATE_MODE = "select"  # 'rate' or 'select'


class CreateTrial(CreateTrialMixin, AudioGibbsTrial):
    snap_slider = SNAP_SLIDER
    autoplay = AUTOPLAY
    debug = DEBUG
    minimal_time = 3.0
    time_estimate = 5.0

    def get_prompt(self, experiment, participant):
        return get_prompt(self)


class SingleRateTrial(RateTrialMixin, ImitationChainTrial):
    time_estimate = 5

    def get_target_answer(self, target):
        return get_target_gibbs_answer(target)

    def show_trial(self, experiment, participant):
        assert len(self.targets) == 1
        target = self.targets[0]
        # in gsp in each node creators listen to the same stimulus, so we can do this
        gsp_trial = self.trial_maker.get_finished_creations(self.node)[0]
        creation = self.get_target_answer(target)

        possible_values = list(np.linspace(RANGE[0], RANGE[1], GRANULARITY))
        slider_idx = possible_values.index(find_nearest(possible_values, creation))
        slider_key = f"slider_stimulus_{slider_idx}"
        events, progress_display = prepare_audio_events(
            [slider_key], expected_duration=AUDIO_DURATION
        )
        return ModularPage(
            "rating",
            get_prompt(self),
            control=PushButtonControl(
                choices=[5, 4, 3, 2, 1],
                labels=[
                    "Excellent match",
                    "Good match",
                    "Fair match",
                    "Poor match",
                    "Bad match",
                ],
                arrange_vertically=False,
            ),
            media=MediaSpec(audio={"batch": gsp_trial.media.audio["slider_stimuli"]}),
            events=events,
            progress_display=progress_display,
            time_estimate=5,
        )

    def format_answer(self, raw_answer, **kwargs):
        return RateTrialMixin.format_answer(self, raw_answer, **kwargs)


class SelectTrial(SelectTrialMixin, ImitationChainTrial):
    time_estimate = 5

    def get_target_answer(self, target):
        return get_target_gibbs_answer(target)

    def show_trial(self, experiment, participant):
        assert len(self.targets) == self.trial_maker.n_rate_stimuli
        answers = [self.get_target_answer(target) for target in self.targets]
        possible_values = list(np.linspace(RANGE[0], RANGE[1], GRANULARITY))

        slider_keys = []
        for observation in answers:
            slider_idx = possible_values.index(
                find_nearest(possible_values, observation)
            )
            slider_key = f"slider_stimulus_{slider_idx}"
            slider_keys.append(slider_key)

        events, progress_display = prepare_audio_events(
            slider_keys, expected_duration=AUDIO_DURATION
        )

        gsp_trial = self.trial_maker.get_finished_creations(self.node)[0]

        # practical for debugging, but in real experiments you should rather do something like this:
        labels = [f"Recording {i + 1}" for i in range(len(self.targets))]
        target_strs = [f"{target}" for target in self.targets]

        return ModularPage(
            "selection",
            get_prompt(self),
            control=PushButtonControl(
                choices=target_strs, labels=labels, arrange_vertically=False
            ),
            media=MediaSpec(audio={"batch": gsp_trial.media.audio["slider_stimuli"]}),
            events=events,
            progress_display=progress_display,
            time_estimate=len(self.targets) * AUDIO_DURATION + 2,
        )


class CreateAndRateNode(CreateAndRateNodeMixin, AudioGibbsNode):
    vector_length = DIMENSIONS
    vector_ranges = [RANGE for _ in range(DIMENSIONS)]
    granularity = GRANULARITY
    n_jobs = 8  # <--- Parallelizes stimulus synthesis into 8 parallel processes at each worker node

    def synth_function(self, vector, output_path, chain_definition):
        custom_synth.synth_stimulus(vector, output_path, chain_definition)

    def summarize_trials(self, trials: list, experiment, participant):
        winning_target = super().summarize_trials(trials, experiment, participant)
        if isinstance(winning_target, CreateAndRateNode):
            # is previous iteration
            return winning_target.definition
        else:
            initial_index = winning_target.initial_index
            active_index = winning_target.active_index
            vector = winning_target.updated_vector.copy()
            vector[active_index] = winning_target.answer
            return {
                "vector": vector,
                "initial_index": initial_index,
                "active_index": active_index,
            }


class CustomCreateAndRateTrialMaker(CreateAndRateTrialMakerMixin, AudioGibbsTrialMaker):
    pass


start_nodes = [
    CreateAndRateNode(
        context={
            "img_url": url,
        }
    )
    for url in main_experiment_urls
]


def make_trial_maker(rate_mode):
    n_trials_per_participant = 3
    n_iterations_per_chain = 2

    include_previous_iteration = True
    if rate_mode == "rate":
        nodes = [start_nodes[0]]
        rater_class = SingleRateTrial
    elif rate_mode == "select":
        nodes = [start_nodes[1]]
        rater_class = SelectTrial
    else:
        raise ValueError("Invalid type")

    target_selection_method = "all" if rate_mode == "select" else "one"
    _id = rate_mode + "_trial_maker"

    return CustomCreateAndRateTrialMaker(
        n_creators=1,
        n_raters=1 + include_previous_iteration,
        node_class=CreateAndRateNode,
        creator_class=CreateTrial,
        rater_class=rater_class,
        include_previous_iteration=include_previous_iteration,
        rate_mode=rate_mode,
        target_selection_method=target_selection_method,
        verbose=True,
        # GSP trial maker parameters
        id_=_id,
        chain_type="across",
        start_nodes=nodes,
        expected_trials_per_participant=n_trials_per_participant,
        max_trials_per_participant=n_trials_per_participant,
        max_nodes_per_chain=n_iterations_per_chain,
        chains_per_experiment=None,  # set to None if chain_type="within"
        balance_across_chains=True,
        check_performance_at_end=True,
        check_performance_every_trial=False,
        propagate_failure=False,
        recruit_mode="n_trials",
        target_n_participants=None,
        wait_for_networks=False,
        allow_revisiting_networks_in_across_chains=True,
    )


##########################################################################################
# Experiment
##########################################################################################


class Exp(psynet.experiment.Experiment):
    label = "Robot Voice demo"

    timeline = Timeline(
        make_trial_maker(RATE_MODE),
    )
