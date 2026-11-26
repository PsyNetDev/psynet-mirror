"""Prepared trials in random node order, using the flanker demo.

A separate file from ``test_prepared_trials``, as each pytest session runs
one experiment directory.
"""

from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.trial.main import Trial

FLANKER = str(Path(__file__).parents[2] / "demos/experiments/flanker")


@pytest.mark.parametrize("experiment_directory", [FLANKER], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_random_order_prepares_each_node_once_and_replaces_failed_trials():
    bot = BotDriver()
    trials = Trial.query.filter_by(participant_id=bot.id)
    while not trials.count():
        bot.take_page()
    prepared = trials.order_by(Trial.id).all()
    assert len(prepared) == 3

    prepared[-1].fail(reason="test")
    db.session.commit()
    bot.run_to_completion()
    nodes = [trial.node_id for trial in trials.filter_by(failed=False)]
    assert len(set(nodes)) == len(nodes) == 16
    assert prepared[-1].node_id in nodes
