import time

import pytest

from psynet.participant import Participant
from psynet.pytest_psynet import (
    bot_class,
    click_finish_button,
    next_page,
    path_to_test_experiment,
)
from psynet.trial.mcmcp import MCMCPNetwork
from psynet.utils import get_config

PYTEST_BOT_CLASS = bot_class()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("mcmcp")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_exp(self, bot_recruits, db_session):
        for participant_id, bot in enumerate(bot_recruits):
            # Python zero-indexes, SQL one-indexes
            participant_id += 1

            driver = bot.driver
            time.sleep(1)

            driver.execute_script(
                "$('html').animate({ scrollTop: $(document).height() }, 0);"
            )
            next_page(driver, "consent")

            # Testing that network.participant works correctly
            # (we are in a within-participant experiment, so each chain
            # should be associated with a single participant).
            network = MCMCPNetwork.query.all()[0]
            assert isinstance(network.participant, Participant)
            assert network.participant.id == participant_id

            # Iterating through the trials
            for i in range(9):
                next_page(driver, "1")

            next_page(driver, "next-button")
            click_finish_button(driver)

    def test_default_variables(self, db_session):
        from psynet.experiment import get_experiment

        exp = get_experiment()
        assert exp.var.max_participant_payment == 25.0
        assert exp.var.hard_max_experiment_payment == 1100.0
        assert exp.var.hard_max_experiment_payment_email_sent is False
        assert exp.var.soft_max_experiment_payment == 1000.0
        assert exp.var.soft_max_experiment_payment_email_sent is False

        config = get_config()
        assert config.get("min_browser_version") == "105.0"
        assert config.get("allow_mobile_devices") is True
        assert config.get("wage_per_hour") == 12.0
        assert config.get("min_reward_for_paid_early_exit") == 0.2
        assert not config.get("show_early_exit_button")
        # Unset by default: Experiment.show_reward asks the recruiter instead.
        assert config.get("show_reward", None) is None
