import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline, randomize
from psynet.utils import get_logger

logger = get_logger()


class Exp(psynet.experiment.Experiment):
    label = "Randomize demo"

    timeline = Timeline(
        randomize(
            logic=[InfoPage(f"{i}", time_estimate=5) for i in range(100)],
        ),
    )

    def test_run_bot(self, bot):
        observed = []
        for i in range(100):
            observed.append(str(bot.get_current_page().prompt))
            bot.take_page()
        assert sorted(observed) == [str(i) for i in range(100)]
        bot.run_to_completion()
