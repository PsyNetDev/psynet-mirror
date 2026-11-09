import pytest

from psynet.bot import BotDriver
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.main import Trial


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("imitation_chain_accumulated")],
    indirect=True,
)
@pytest.mark.usefixtures("launched_experiment")
def test_trial_records_time_and_response_of_its_own_pages():
    bot = BotDriver()
    bot.run_until(lambda bot: bot.current_page_label == "number_1")
    with pytest.raises(RuntimeError, match="rejected"):
        bot.take_page(response="INVALID_RESPONSE")
    bot.take_experiment()

    trials = Trial.query.order_by(Trial.id).all()
    assert len(trials) == 5
    for trial in trials:
        # Bots report each page's time estimate: 5 + 3 + 3 seconds, excluding
        # the rejected attempt, the feedback page and the pages after the trial.
        assert trial.time_taken == 11
        assert trial.response.question == "number_2"
        assert trial.response.successful_validation
