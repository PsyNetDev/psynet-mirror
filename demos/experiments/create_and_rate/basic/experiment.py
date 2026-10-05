##########################################################################################
# Imports
##########################################################################################
from markupsafe import Markup

import psynet.experiment
from psynet.modular_page import ImagePrompt, ModularPage, PushButtonControl, TextControl
from psynet.timeline import Timeline, switch
from psynet.trial.create_and_rate import (
    CreateAndRateNode,
    CreateAndRateTrialMakerMixin,
    CreateTrialMixin,
    RateTrialMixin,
    SelectTrialMixin,
)
from psynet.trial.imitation_chain import ImitationChainTrial, ImitationChainTrialMaker
from psynet.utils import get_logger

logger = get_logger()


def animal_prompt(text, img_url):
    return ImagePrompt(
        url=img_url,
        text=Markup(text),
        width="300px",
        height="300px",
    )


class CreateTrial(CreateTrialMixin, ImitationChainTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        return ModularPage(
            "create_trial",
            animal_prompt(text="Describe the animal", img_url=self.context["img_url"]),
            TextControl(),
            time_estimate=self.time_estimate,
        )


class SingleRateTrial(RateTrialMixin, ImitationChainTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        assert self.trial_maker.target_selection_method == "one"

        assert len(self.targets) == 1
        target = self.targets[0]
        creation = self.get_target_answer(target)
        return ModularPage(
            "rate_trial",
            animal_prompt(
                text=f"How well does this description match the animal?<br><strong>{creation}</strong>",
                img_url=self.context["img_url"],
            ),
            PushButtonControl(
                choices=[1, 2, 3, 4, 5],
                labels=["not at all", "a little", "somewhat", "very", "perfectly"],
                arrange_vertically=False,
            ),
        )


class SelectTrial(SelectTrialMixin, ImitationChainTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        target_strs = [f"{target}" for target in self.targets]
        answers = [self.get_target_answer(target) for target in self.targets]
        return ModularPage(
            "select_trial",
            animal_prompt(
                text="Which of these descriptions is the best?",
                img_url=self.context["img_url"],
            ),
            PushButtonControl(
                choices=target_strs,
                labels=answers,
            ),
        )


class CreateAndRateTrialMaker(CreateAndRateTrialMakerMixin, ImitationChainTrialMaker):
    pass


##########################################################################################
# Experiment
##########################################################################################


def get_trial_maker(option):
    rater_class = SingleRateTrial
    n_creators = 2
    n_raters = 2
    rate_mode = "rate"
    include_previous_iteration = True
    target_selection_method = "one"

    if option == "include_previous_iteration":
        n_creators = 1
        pass
    elif option == "rate":
        include_previous_iteration = False
    elif option == "select":
        rater_class = SelectTrial
        n_raters = 3
        target_selection_method = "all"
        rate_mode = "select"
    else:
        raise ValueError(f"Unknown option: {option}")

    seed_definition = "initial creation" if include_previous_iteration else {}
    start_nodes = [
        CreateAndRateNode(context={"img_url": "static/dog.jpg"}, seed=seed_definition)
    ]

    return CreateAndRateTrialMaker(
        n_creators=n_creators,
        n_raters=n_raters,
        node_class=CreateAndRateNode,
        creator_class=CreateTrial,
        rater_class=rater_class,
        # mixin params
        include_previous_iteration=include_previous_iteration,
        rate_mode=rate_mode,
        target_selection_method=target_selection_method,
        verbose=True,  # for the demo
        # trial_maker params
        id_=option + "_trial_maker",
        chain_type="across",
        expected_trials_per_participant=len(start_nodes),
        max_trials_per_participant=len(start_nodes),
        start_nodes=start_nodes,
        chains_per_experiment=len(start_nodes),
        balance_across_chains=False,
        check_performance_at_end=True,
        check_performance_every_trial=False,
        propagate_failure=False,
        recruit_mode="n_trials",
        target_n_participants=None,
        wait_for_networks=False,
        max_nodes_per_chain=10,
    )


available_demos = ["include_previous_iteration", "rate", "select"]
branches = {demo_name: get_trial_maker(demo_name) for demo_name in available_demos}


class Exp(psynet.experiment.Experiment):
    label = "Basic Create and Rate Experiment"

    timeline = Timeline(
        ModularPage(
            "pick_demo_page",
            "Pick a demo you are interested in.",
            PushButtonControl(
                choices=available_demos,
                labels=[
                    "Rate creation + previous iteration",
                    "Rate two creations",
                    "Select from two creations + previous iteration",
                ],
            ),
            time_estimate=1,
        ),
        switch(
            "pick_demo_switch",
            lambda participant: participant.answer,
            branches=branches,
            fix_time_credit=False,
        ),
    )
