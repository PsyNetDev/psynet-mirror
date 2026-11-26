import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_the_leave_offer_is_prepared_when_the_participant_asks_to_leave():
    bot = BotDriver()
    experiment = get_experiment()
    while not bot.get_current_page().early_exit_available(
        experiment, Participant.query.get(bot.id)
    ):
        bot.take_page()
    participant = Participant.query.get(bot.id)
    # Serving a page prepares no offer, so pages rendered before they are
    # served can offer Leave too.
    assert participant.exit_plan is None

    base_url = bot.experiment.base_url
    prepare = f"{base_url}/prepare_early_exit_plan/{participant.assignment_id}"
    stale = bot.http_session.post(prepare, json={"page_uuid": "an-earlier-page"})
    assert stale.status_code == 409
    assert bot.http_session.post(prepare, json={}).status_code == 409
    offer = bot.http_session.post(prepare, json={"page_uuid": participant.page_uuid})
    assert offer.json()["confirmation"]["title"] == "Leave without finishing?"

    leave = bot.http_session.post(
        f"{base_url}/execute_early_exit_plan/{participant.assignment_id}",
        json={"plan_id": offer.json()["offer_id"]},
    )
    assert leave.ok
    db.session.expire_all()
    assert Participant.query.get(bot.id).early_exited
    again = bot.http_session.post(prepare, json={"page_uuid": participant.page_uuid})
    assert again.status_code == 409
