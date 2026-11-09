# This demo illustrates some simple usage of custom SQLAlchemy classes in the context of a PsyNet experiment.
# We define a new table called 'coin', and store coins in it as the experiment progresses.

from dallinger import db
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

import psynet.experiment
from psynet.data import SQLBase, SQLMixin, register_table
from psynet.modular_page import PushButtonControl
from psynet.page import InfoPage, ModularPage
from psynet.participant import Participant
from psynet.timeline import CodeBlock, PageMaker, Timeline, join, while_loop


@register_table
class Coin(SQLBase, SQLMixin):
    __tablename__ = "coin"

    participant = relationship(Participant, backref="all_coins")
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)

    def __init__(self, participant):
        self.participant = participant
        self.participant_id = participant.id


def collect_coin():
    return CodeBlock(_collect_coin)


def _collect_coin(participant):
    coin = Coin(participant)
    db.session.add(coin)


def report_n_coins():
    return PageMaker(_report_n_coins, time_estimate=5)


def _report_n_coins(participant):
    coins = participant.all_coins
    n_coins = len(coins)
    return InfoPage(f"You currently have {n_coins} coin(s).", time_estimate=5)


def check_continue():
    return ModularPage(
        "check_continue",
        "Would you like to collect another coin?",
        PushButtonControl(["Yes", "No"]),
        save_answer="collecting_coins",
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Custom table (simple) demo"

    timeline = Timeline(
        CodeBlock(lambda participant: participant.var.set("collecting_coins", "Yes")),
        while_loop(
            lambda participant: participant.var.collecting_coins == "Yes",
            logic=join(
                collect_coin(),
                report_n_coins(),
                check_continue(),
            ),
            expected_repetitions=3,
        ),
    )
