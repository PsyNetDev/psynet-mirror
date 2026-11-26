# This demo shows the vocabulary tests WikiVocab and BibleVocab. The tests contain of a list of real and fake words and
# participants have to indicate for each word if it's real or fake.
# WikiVocab is made from Wikipedia and is generally of a better quality than BibleVocab, which is made from the Bible.
# However, BibleVocab is available for more languages.

import requests

import psynet.experiment
from psynet.bot import Bot
from psynet.page import InfoPage, SuccessfulEndPage
from psynet.prescreen import BibleVocab, WikiVocab
from psynet.timeline import Timeline
from psynet.utils import get_translator

_ = get_translator()


class Exp(psynet.experiment.Experiment):
    label = "Vocabulary test demo"
    test_n_bots = 2

    timeline = Timeline(
        InfoPage(
            (
                _("Welcome to the experiment!")
                + " "
                + _(
                    "In this experiment, we will test your vocabulary knowledge in two languages."
                )
            ),
            time_estimate=5,
        ),
        WikiVocab(
            "nl",
            performance_threshold_per_trial=0,
            n_items=30,
        ),
        BibleVocab(
            "nl",
            show_instructions=False,
            n_repeat_items=4,
            performance_check_type="consistency",
            performance_threshold_per_trial=0,
        ),
        InfoPage(
            (_("Now we move on to English")),
            time_estimate=5,
        ),
        WikiVocab(
            "en",
            n_trials=2,
            show_instructions=False,
            performance_threshold_per_trial=0,
        ),
        SuccessfulEndPage(),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        from psynet.experiment import get_experiment

        assert not bot.failed
        assert not bot.sync_group_links
        trials = bot.all_trials
        assert len(trials) == 30 + 34 + 60
        assert all(
            t.complete and t.finalized and t.answer in ("real", "fake") for t in trials
        )
        assert all(t.presented_at for t in trials)

        for label, size, repeats in [
            ("wikivocab_nl", 30, 0),
            ("biblevocab_nld", 30, 4),
            ("wikivocab_en", 60, 0),
        ]:
            items = sorted(
                (t for t in trials if t.trial_maker_id == label),
                key=lambda t: t.position,
            )
            assert [t.position for t in items] == list(range(size + repeats))
            assert len({t.node_id for t in items[:size]}) == size
            assert all(
                t.node_id in {original.node_id for original in items[:size]}
                for t in items[size:]
            )
            assert (
                sum(t.definition["correct_answer"] == "correct" for t in items[:size])
                == size // 2
            )

        trial = next(t for t in trials if t.trial_maker_id == "wikivocab_nl")
        asset = trial.node.assets["image"]
        url = get_experiment().asset_storage._prepare_url_for_http_export(asset.url)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        assert response.content.startswith(bytes.fromhex("89504e470d0a1a0a"))
