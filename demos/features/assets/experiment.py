import random
import tempfile
import time

from markupsafe import Markup

import psynet.experiment
from psynet.asset import FileAsset, asset
from psynet.modular_page import AudioPrompt, TextControl
from psynet.page import InfoPage, ModularPage
from psynet.timeline import CodeBlock, Module, PageMaker, Timeline


def slow_computation(path, n, k):
    time.sleep(1)
    x = random.sample(range(n), k)
    with open(path, "w") as f:
        f.write(str(x))


headphone_assets = {
    "stimulus_1": asset(
        "https://s3.amazonaws.com/headphone-check/antiphase_HC_ISO.wav"
    ),
    "stimulus_2": asset(
        "https://s3.amazonaws.com/headphone-check/antiphase_HC_IOS.wav"
    ),
    "stimulus_3": asset(
        "https://s3.amazonaws.com/headphone-check/antiphase_HC_SOI.wav"
    ),
}

misc_assets = {
    "slow_computation": asset(
        slow_computation, arguments=dict(n=200, k=5), extension=".txt"
    ),
    "psynet_logo": asset(
        "https://gitlab.com/computational-audition-lab/psynet/-/raw/master/psynet/resources/logo.svg",
    ),
    "headphone_check_folder": asset(
        "https://s3.amazonaws.com/headphone-check", is_folder=True
    ),
    "config": asset("config.txt"),
    "bier": asset("bier.wav"),
}


def save_text(participant):
    text = participant.answer
    with tempfile.NamedTemporaryFile("w") as file:
        file.write(text)
        file.flush()
        _asset = asset(
            file.name,
            local_key="text_input",
            extension=".txt",
            description="Some text that the participant filled out",
            parent=participant,
        )
        _asset.deposit()


class Exp(psynet.experiment.Experiment):
    label = "Assets demo"

    timeline = Timeline(
        Module(
            "headphone_check",
            [
                PageMaker(
                    lambda assets, i=i: ModularPage(
                        f"headphone_check_{i}",
                        AudioPrompt(
                            assets[f"stimulus_{i}"],
                            text=f"This is headphone check stimulus number {i}.",
                        ),
                    ),
                    time_estimate=5,
                )
                for i in range(1, 4)
            ],
            assets=headphone_assets,
        ),
        Module(
            "misc",
            PageMaker(
                lambda assets: InfoPage(
                    Markup(
                        (
                            "<strong>The following information is pulled from config.txt:</strong>\n\n"
                            + assets["config"].read_text()
                        ).replace("\n", "<br>")
                    )
                ),
                time_estimate=5,
            ),
            ModularPage(
                "text_input",
                "Please enter some text. It will be saved to a text file and stored as an experiment asset.",
                TextControl(),
                time_estimate=5,
            ),
            CodeBlock(save_text),
            assets=misc_assets,
        ),
    )

    def test_experiment(self):
        super().test_experiment()

        # Files prepared before launch are not exported; files created during the run are.
        config = FileAsset.query.filter_by(local_key="config").one()
        assert not config.created_during_experiment
        text_inputs = FileAsset.query.filter_by(local_key="text_input").all()
        assert text_inputs
        assert all(a.created_during_experiment for a in text_inputs)
