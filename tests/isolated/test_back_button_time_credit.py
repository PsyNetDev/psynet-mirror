import json
from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.participant import Participant

EXPERIMENT = str(Path(__file__).parents[1] / "experiments/fix_time_credit")


def _go_back(bot):
    return bot.http_session.post(
        f"{bot.experiment.base_url}/response",
        data={
            "json": json.dumps(
                {
                    "participant_id": bot.id,
                    "page_uuid": bot.current_page_uuid,
                    "raw_answer": None,
                    "metadata": {},
                    "back": True,
                }
            )
        },
    ).json()


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_back_restores_the_time_credit_inside_a_fixed_time_credit():
    bot = BotDriver()
    bot.run_until(lambda bot: "Back test: first page" in bot.current_page_text)
    before = Participant.query.get(bot.id)
    credit, progress = before.time_credit, before.progress
    bot.take_page()
    # The first page gave only the 5 seconds left in the fixed time credit.
    assert Participant.query.get(bot.id).time_credit == credit + 5

    for _ in range(2):
        assert _go_back(bot)["submission"] == "approved"
        db.session.expire_all()
        participant = Participant.query.get(bot.id)
        assert (participant.time_credit, participant.progress) == (credit, progress)
        bot.take_page()
