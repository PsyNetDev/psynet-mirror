import random
from typing import List, Union

from dominate import tags
from markupsafe import Markup

import psynet.experiment
from psynet.bot import Bot, BotDriver, advance_past_wait_pages
from psynet.experiment import get_trial_maker
from psynet.modular_page import ModularPage, Prompt, SliderControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import SimpleGrouper, SyncGroup
from psynet.timeline import Timeline, join
from psynet.trial.gibbs import GibbsNode, GibbsTrial, GibbsTrialMaker
from psynet.utils import as_plain_text, get_logger

logger = get_logger()

TARGETS = ["tree", "rock", "carrot", "banana"]
COLORS = ["red", "green", "blue"]


class ColorSliderPage(ModularPage):
    def __init__(
        self,
        label: str,
        prompt: Union[str, Markup],
        selected_idx: int,
        starting_values: List[int],
        reverse_scale: bool,
        directional: bool,
        time_estimate=None,
        **kwargs,
    ):
        assert 0 <= selected_idx < len(COLORS)
        self.prompt = prompt
        self.selected_idx = selected_idx
        self.starting_values = starting_values

        not_selected_idxs = list(range(len(COLORS)))
        not_selected_idxs.remove(selected_idx)
        not_selected_colors = [COLORS[i] for i in not_selected_idxs]
        not_selected_values = [starting_values[i] for i in not_selected_idxs]
        hidden_inputs = dict(zip(not_selected_colors, not_selected_values))
        kwargs["template_arg"] = {
            "hidden_inputs": hidden_inputs,
        }
        super().__init__(
            label,
            Prompt(prompt),
            control=SliderControl(
                start_value=starting_values[selected_idx],
                min_value=0,
                max_value=255,
                slider_id=COLORS[selected_idx],
                reverse_scale=reverse_scale,
                directional=directional,
                template_filename="color-slider.html",
                template_args={
                    "hidden_inputs": hidden_inputs,
                },
                continuous_updates=False,
                bot_response=lambda: random.randint(0, 255),
            ),
            time_estimate=time_estimate,
            css_links=["/static/color-slider.css"],
            js_page_modules=["/static/color-slider.js"],
        )


class CustomTrial(GibbsTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        return join(
            self.see_last_trial_responses(participant) if self.degree > 0 else None,
            self.choose_response(),
        )

    def choose_response(self):
        target = self.context["target"]

        prompt = tags.span()
        with prompt:
            tags.span(
                "Adjust the slider to match the following word as well as possible: "
            )
            tags.strong(target)

        return ColorSliderPage(
            "color_trial",
            prompt,
            starting_values=self.initial_vector,
            selected_idx=self.active_index,
            reverse_scale=self.reverse_scale,
            directional=False,
        )

    def see_last_trial_responses(self, participant: Participant):
        last_node = self.node.parent
        last_trials = last_node.alive_trials
        last_trials.sort(key=lambda t: t.participant_id)
        try:
            participant_answer = [
                t.answer for t in last_trials if t.participant == participant
            ][0]
        except IndexError:
            participant_answer = None
        other_participant_answers = [
            t.answer for t in last_trials if t.participant != participant
        ]

        html = tags.span()
        with html:
            if participant_answer is not None:
                tags.p(f"You chose: {participant_answer}")
            tags.p("Other participants chose:")
            with tags.ul():
                for response in other_participant_answers:
                    tags.li(response)
            tags.p(
                f"The summarized response was {last_node.var.summarize_trials_output}."
            )

        return InfoPage(html)


class CustomNode(GibbsNode):
    vector_length = 3

    def random_sample(self, i):
        return random.randint(0, 255)


trial_maker = GibbsTrialMaker(
    id_="gibbs_demo",
    start_nodes=lambda: [CustomNode(context={"target": random.sample(TARGETS, 1)[0]})],
    sync_group_type="gibbs",
    trial_class=CustomTrial,
    node_class=CustomNode,
    chain_type="within",
    expected_trials_per_participant=4,
    max_trials_per_participant=4,
    max_nodes_per_chain=4,
    chains_per_participant=1,
    recruit_mode="n_participants",
    target_n_participants=3,
    # propagate_failure means that when a trial fails the chain is aggressively pruned
    # such that no nodes are 'contaminated' by the failed trial. This is often desirable,
    # but if we want to make maximum use of participant trials, we can set propagate_failure=False.
    propagate_failure=False,
    wait_for_networks=True,
)


def is_group_joinable(group: SyncGroup, participant: Participant):
    trial_maker_id = "gibbs_demo"

    leader = group.leader
    leader_still_in_trial_maker = leader.module_id == trial_maker_id
    if not leader_still_in_trial_maker:
        return False

    leader_n_trials_in_trial_maker = len(
        [t for t in leader.all_trials if t.trial_maker_id == trial_maker_id]
    )
    leader_n_trials_left = (
        get_trial_maker(trial_maker_id).max_trials_per_participant
        - leader_n_trials_in_trial_maker
    )

    return leader_n_trials_left > 1


class Exp(psynet.experiment.Experiment):
    label = "Gibbs within sync demo"

    timeline = Timeline(
        InfoPage("Welcome to the experiment!", time_estimate=5),
        SimpleGrouper(
            group_type="gibbs",
            initial_group_size=3,
            join_existing_groups=True,
            join_criterion=is_group_joinable,
        ),
        trial_maker,
    )

    test_n_bots = 4

    def test_serial_run_bots(self, bots: List[BotDriver]):
        from psynet.page import WaitPage

        original_bots = bots[:3]

        for bot in original_bots:
            assert bot.get_current_page().content == "Welcome to the experiment!"
            bot.take_page()
            assert isinstance(bot.get_current_page(), WaitPage)

        # Send the first three bots into the trial maker
        advance_past_wait_pages(original_bots)

        # Trial 1 (degree = 0)
        for bot, response in zip(original_bots, [100, 110, 120]):
            page = bot.get_current_page()
            assert page.label == "color_trial"
            bot.take_page(response=response)
            assert isinstance(bot.get_current_page(), WaitPage)

        # Going now to the next trial;
        # Trial 2 (degree = 1)
        advance_past_wait_pages(original_bots, max_iterations=30)

        # Check that the trials have been aggregated appropriately
        page = bots[0].get_current_page()
        info_message = "You chose: 100 Other participants chose: * 110 * 120 The summarized response was 110."
        assert as_plain_text(page.prompt.text) == info_message

        # Now we make one of the bots fail during a trial
        bots[0].fail(reason="simulated_failure")
        group = SyncGroup.query.one()
        assert group.n_active_participants < group.min_group_size

        # Bring in a new bot to replace the failed one
        new_bot = bots[3]
        assert new_bot.get_current_page().content == "Welcome to the experiment!"

        # If we send the new bot into the trial maker, it should be able to join the group
        new_bot.take_page()

        # Need to refresh the group to get the latest state
        group = SyncGroup.query.one()
        assert Bot.query.get(new_bot.id) in group.participants

        # Now the participant should be waiting at the prepare_trial barrier.
        # The other two bots need to finish the previous trial before this new trial can begin
        assert isinstance(new_bot.get_current_page(), WaitPage)
        assert "prepare_trial" in new_bot.active_barriers

        # Let's have them finish the trial, then
        for bot in [bots[1], bots[2]]:
            page = bot.get_current_page()
            assert isinstance(page, InfoPage)
            bot.take_page()

            page = bot.get_current_page()
            assert page.label == "color_trial"
            bot.take_page()

        # Now all bots should be ready for the next trial
        # Trial 3 (degree = 2)
        bots = [bots[1], bots[2], new_bot]

        advance_past_wait_pages(bots, max_iterations=30)

        for bot in bots:
            assert bot.current_trial is not None
            assert isinstance(bot.get_current_page(), InfoPage)

        # They should all be assigned to the same node
        assert len(set([bot.current_node.id for bot in bots])) == 1

        # Great, the new bot has successfully joined the team! They can go ahead and finish the experiment now.
        # There should be two more trials to complete, including this one, because max_nodes_per_chain == 4.
        # We want to keep an eye out for the new bot, and make sure it follows the other two bots in finishing the
        # trial maker, which will mean it only taking three trials instead of four.

        for remaining_nodes in range(2):
            for bot in bots:
                page = bot.get_current_page()
                assert isinstance(page, InfoPage), (
                    f"Bot {bot.id} unexpectedly saw {page} instead of an InfoPage, on remaining_nodes = {remaining_nodes}."
                )
                bot.take_page()

                page = bot.get_current_page()
                assert page.label == "color_trial"
                bot.take_page()
            advance_past_wait_pages(bots, max_iterations=30)

        for bot in bots:
            page = bot.get_current_page()
            text = as_plain_text(page.prompt.text)
            assert "That's the end of the experiment!" in text

    def test_check_bot(self, bot: Bot, **kwargs):
        assert not bot.failed or bot.failed_reason == "simulated_failure"

    # Uncomment the following to run bots in the background of the experiment.
    # @staticmethod
    # @scheduled_task("interval", seconds=1.0, max_instances=1)
    # def bot_launcher():
    #     from psynet.experiment import get_experiment, is_experiment_launched

    #     n_bots = Bot.query.filter_by(status="working").count()
    #     if is_experiment_launched() and n_bots < 3:  # allow only fixed number of bots
    #         WorkerAsyncProcess(
    #             function=get_experiment().run_bot, arguments={"time_factor": 0.9}
    #         )
    #         db.session.commit()
