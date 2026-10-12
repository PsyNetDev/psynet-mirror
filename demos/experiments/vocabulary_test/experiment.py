# This demo shows the vocabulary tests WikiVocab and BibleVocab. The tests contain of a list of real and fake words and
# participants have to indicate for each word if it's real or fake.
# WikiVocab is made from Wikipedia and is generally of a better quality than BibleVocab, which is made from the Bible.
# However, BibleVocab is available for more languages.
import random

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
        trials = bot.all_trials
        assert len(trials) == 4  # 1 wikivocab + 1 biblevocab nl + 2x wikivocab en

        # polvanrijn's original version of this code checked for uniqueness of hashes
        # across all trials. This seems problematic as perhaps the same word appears
        # in multiple datasets; if so, this would cause the test to stochastically fail.
        for trial in trials:
            visited_hashes = [item["hash"] for item in trial.answer]
            # Make sure the participant doesn't revisit the same asset
            assert len(visited_hashes) == len(set(visited_hashes))

        assets = trials[0].assets
        assert len(assets) == 30
        asset_key = random.sample(list(assets.keys()), 1)[0]
        asset = assets[asset_key]
        exp = get_experiment()
        url = exp.asset_storage._prepare_url_for_http_export(asset.url)
        assert url.startswith("http")
        assert requests.get(url).status_code == 200
