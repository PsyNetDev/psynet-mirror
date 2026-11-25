import psynet.experiment
from psynet.page import InfoPage, SuccessfulEndPage
from psynet.prescreen import WikiVocab
from psynet.timeline import Timeline

N_ITEMS = 30
N_REPEAT_ITEMS = 0


class Exp(psynet.experiment.Experiment):
    label = "Vocabulary test screening"
    test_n_bots = 1

    timeline = Timeline(
        WikiVocab(
            "en",
            n_trials=2,
            n_items=N_ITEMS,
            n_repeat_items=N_REPEAT_ITEMS,
            present_as_image=False,
            show_instructions=False,
            performance_threshold_per_trial=0.99,
        ),
        InfoPage("Not reached by a bot answering at random.", time_estimate=1),
        SuccessfulEndPage(),
    )

    def test_check_bot(self, bot, **kwargs):
        # Random answers fail the first form, so the second is never answered.
        assert bot.failed
        assert "performance_check" in bot.failure_tags
        answered = [trial for trial in bot.all_trials if trial.complete]
        assert len(answered) == N_ITEMS + N_REPEAT_ITEMS
