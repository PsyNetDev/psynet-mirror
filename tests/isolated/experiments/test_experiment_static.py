import time
from collections import Counter

import pytest

from psynet.participant import Participant
from psynet.pytest_psynet import (
    assert_text,
    bot_class,
    click_finish_button,
    next_page,
    path_to_test_experiment,
)
from psynet.trial.static import StaticNetwork, StaticNode, StaticTrial

PYTEST_BOT_CLASS = bot_class()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_exp(self, bot_recruits, db_session, trial_maker):
        for participant, bot in enumerate(bot_recruits):
            driver = bot.driver
            time.sleep(1)

            networks = StaticNetwork.query.filter_by(trial_maker_id="animals").all()
            nodes = StaticNode.query.all()

            assert networks[0].type == "psynet.trial.static.StaticNetwork"
            assert nodes[0].type == "psynet.trial.static.StaticNode"

            assert len(networks) == 12
            assert len(nodes) == 12

            assert set([n.block for n in networks]) == {"A", "B", "C"}

            assert_text(driver, "trial-position", "Trial 1")
            next_page(driver, "A little")

            trial = StaticTrial.query.filter_by(id=1).one()
            assert trial.answer == "A little"
            assert trial.type == "dallinger_experiment.experiment.AnimalTrial"

            assert_text(driver, "trial-position", "Trial 2")

            next_page(driver, "Very much")
            trial = StaticTrial.query.filter_by(id=2).one()
            assert trial.answer == "Very much"
            assert_text(driver, "trial-position", "Trial 3")

            n_remaining_trials = 4
            n_repeat_trials = 3

            for _ in range(n_remaining_trials + n_repeat_trials):
                next_page(driver, "Very much")

            assert_text(
                driver,
                "main-body",
                "You finished the animal questions! Your score was 9. Next",
            )

            trials = StaticTrial.query.all()

            trials_by_block = Counter(
                [
                    trial.block
                    for trial in trials
                    if trial.participant_id == 1 and not trial.is_repeat_trial
                ]
            )
            assert list(trials_by_block.values()) == [2, 2, 2]  # 2 trials in each block

            trials_by_node = Counter(
                [
                    trial.node_id
                    for trial in trials
                    if trial.participant_id == 1 and not trial.is_repeat_trial
                ]
            )
            assert list(trials_by_node.values()) == [
                1,
                1,
                1,
                1,
                1,
                1,
            ]  # no node comes twice

            assert len([t for t in trials if t.is_repeat_trial]) == 3  # 3 repeat trials

            participant = Participant.query.filter_by(id=1).one()
            p_trials = trial_maker.get_participant_trials(participant=participant)

            assert len(p_trials) == 9
            assert [
                trial.position for trial in sorted(p_trials, key=lambda trial: trial.id)
            ] == list(range(9))
            assert [
                trial.id
                for trial in StaticTrial.query.filter_by(
                    participant_id=participant.id,
                    trial_maker_id="animals",
                ).order_by(StaticTrial.position)
            ] == [trial.id for trial in sorted(p_trials, key=lambda trial: trial.id)]
            for t in p_trials:
                assert t.participant_id == 1
                assert t.trial_maker_id == "animals"
                assert t.time_credit_from_trial == 3
                assert t.time_taken > 0

            next_page(driver, "next-button")

            # 9 * 1 cent reward for individual trials
            # + 9 dollars reward at the end
            # = 9.09
            assert_text(
                driver,
                "main-body",
                """
                That\'s the end of the experiment! You will receive a reward of $0.13
                for the time you spent on the experiment. You have also been awarded a performance reward of $9.09!
                Thank you for taking part.
                Please click "Finish" to finalize the session. Finish
                """,
            )

            click_finish_button(driver)
