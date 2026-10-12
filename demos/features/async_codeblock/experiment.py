import time

from dallinger import db

import psynet.experiment
from psynet.bot import Bot
from psynet.timeline import AsyncCodeBlock, CodeBlock, Timeline


def set_participant_var1(participant):
    time.sleep(1)
    participant.var.set("async1", "ASYNC 1")


def set_participant_var2(participant):
    time.sleep(1)
    participant.var.set("async2", "ASYNC 2")


class Exp(psynet.experiment.Experiment):
    label = "Demo demonstrating asynchronous CodeBlock execution"

    timeline = Timeline(
        CodeBlock(lambda participant: participant.var.set("t1", time.time())),
        AsyncCodeBlock(
            set_participant_var1,
            wait=True,
            expected_wait=1.0,
        ),
        CodeBlock(lambda participant: participant.var.set("t2", time.time())),
        AsyncCodeBlock(
            set_participant_var2,
            wait=False,
        ),
        CodeBlock(lambda participant: participant.var.set("t3", time.time())),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        # Wait a little to ensure that the async code block is finished
        time.sleep(2)

        # Refresh the bot object so that it reflects the latest database state
        db.session.commit()

        assert bot.var.async1 == "ASYNC 1"
        assert bot.var.async2 == "ASYNC 2"

        assert bot.var.t2 - bot.var.t1 > 1.0
        assert bot.var.t3 - bot.var.t2 < 0.25
