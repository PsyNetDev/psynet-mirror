import random

import psynet.experiment
from psynet.asset import Asset, ExternalAsset
from psynet.consent import MainConsent
from psynet.page import InfoPage
from psynet.timeline import Module, PageMaker, Timeline
from psynet.utils import get_logger

# The purpose of this experiment is to test whether PsyNet can handle many External Assets in the same
# experiment without taking unnecessarily long to deploy.


logger = get_logger()

n_assets = 10000


class Exp(psynet.experiment.Experiment):
    label = "Test many external assets"

    timeline = Timeline(
        MainConsent(),
        Module(
            "asset_test",
            PageMaker(
                lambda: InfoPage(
                    f"Here's an asset for you: {Asset.query.get(random.randint(1, n_assets)).url}",
                ),
                time_estimate=5,
            ),
            assets={
                f"asset_{i}": ExternalAsset(url=f"https://google.com/images/asset_{i}")
                for i in range(n_assets)
            },
        ),
        InfoPage("You finished the experiment!", time_estimate=0),
    )
