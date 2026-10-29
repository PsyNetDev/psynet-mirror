import psynet.experiment
from psynet.bot import Bot
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import CodeBlock, PageMaker, Timeline, for_loop, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import get_logger

logger = get_logger("experiment")


def animal_page(animal, time_estimate, bot_response):
    return ModularPage(
        animal,
        f"How much do you like the following animal: {animal}?",
        PushButtonControl(
            ["Not at all", "A little", "Very much"],
        ),
        time_estimate=time_estimate,
        bot_response=bot_response,
    )


def color_page(color, time_estimate, bot_response):
    return ModularPage(
        color,
        f"How much do you like {color}?",
        PushButtonControl(
            ["Not at all", "A little", "Very much"],
        ),
        time_estimate=time_estimate,
        bot_response=bot_response,
    )


nodes_1 = [
    StaticNode(
        definition={"animal": animal},
        block=block,
    )
    for animal in ["cats", "dogs", "fish", "ponies"]
    for block in ["A", "B", "C"]
]


class AnimalTrial(StaticTrial):
    time_estimate = 10
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        animal = self.definition["animal"]
        return join(
            ModularPage(
                "kindness",
                f"How kind is the following animal: {animal}",
                PushButtonControl(["Not at all", "A little", "Very much"]),
                time_estimate=5,
                bot_response="Very much",
            ),
            ModularPage(
                "bravery",
                f"How brave is the following animal: {animal}",
                PushButtonControl(["Not at all", "A little", "Very much"]),
                time_estimate=5,
                bot_response="A little",
            ),
        )


trial_maker_1 = StaticTrialMaker(
    id_="animals",
    trial_class=AnimalTrial,
    nodes=nodes_1,
    expected_trials_per_participant=3,
    max_trials_per_participant=3,
    max_trials_per_block=1,
    target_n_participants=1,
    target_trials_per_node=None,
    recruit_mode="n_participants",
)

part_1_logic = PageMaker(
    lambda: join(
        animal_page("dog", time_estimate=5, bot_response="Very much"),
        color_page("red", time_estimate=5, bot_response="A little"),
    ),
    time_estimate=10,
    accumulate_answers=True,
)


def part_1_check(participant):
    if isinstance(participant, Bot):
        assert participant.answer == {"dog": "Very much", "red": "A little"}


part_1 = join(
    part_1_logic,
    CodeBlock(part_1_check),
)


def part_2_check(participant):
    if isinstance(participant, Bot):
        assert len(participant.alive_trials) == 3
        trial = participant.alive_trials[0]
        assert trial.answer == {"kindness": "Very much", "bravery": "A little"}
        assert trial.to_dict()["kindness"] == "Very much"
        assert trial.to_dict()["bravery"] == "A little"


part_2 = join(
    trial_maker_1,
    CodeBlock(part_2_check),
)

part_3_logic = PageMaker(
    lambda: join(
        InfoPage(
            "I'm going to ask you the same question 3 times in a row.", time_estimate=5
        ),
        for_loop(
            label="Repeat 3 times",
            iterate_over=lambda: range(3),
            logic=lambda _: animal_page(
                "dog", time_estimate=5, bot_response="Very much"
            ),
            time_estimate_per_iteration=5,
        ),
    ),
    accumulate_answers=True,
    time_estimate=20,
)


def part_3_check(participant):
    if isinstance(participant, Bot):
        assert participant.answer == {
            "dog": "Very much",
            "dog_1": "Very much",
            "dog_2": "Very much",
        }


part_3 = join(
    part_3_logic,
    CodeBlock(part_3_check),
)

part_4_logic = PageMaker(
    lambda: join(
        animal_page("cat", time_estimate=5, bot_response="A little"),
        # Earlier answers are already in participant.answer, and a nested
        # accumulating page maker adds its answers to the same dict.
        PageMaker(
            lambda participant: color_page(
                "blue" if participant.answer["cat"] == "A little" else "green",
                time_estimate=5,
                bot_response="Very much",
            ),
            time_estimate=5,
            accumulate_answers=True,
        ),
    ),
    accumulate_answers=True,
    time_estimate=10,
)


def part_4_check(participant):
    if isinstance(participant, Bot):
        assert participant.answer == {"cat": "A little", "blue": "Very much"}


part_4 = join(
    part_4_logic,
    CodeBlock(part_4_check),
)


class Exp(psynet.experiment.Experiment):
    label = "Accumulate answers demo"

    timeline = Timeline(
        part_1,
        part_2,
        part_3,
        part_4,
    )
