import pytest

from psynet.bot import Bot, BotDriver
from psynet.pytest_psynet import path_to_demo_feature


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_feature("bot")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_exp(self):
        bots = [BotDriver() for _ in range(2)]

        for bot in bots:
            bot.take_experiment()

        # Order by id: failing a participant UPDATEs the row, so an unordered
        # SELECT can return the failed bot first.
        bots = Bot.query.order_by(Bot.id).all()

        assert [bot.id for bot in bots] == [1, 2]

        assert not bots[0].failed
        assert bots[1].failed

        bot_1_answers = [r.answer for r in bots[0].all_responses]

        assert bot_1_answers[0] == "Fixed response"
        assert bot_1_answers[1].startswith("Stochastic response")
        assert (
            bot_1_answers[2] == "This response came from the CustomTextControl method."
        )
