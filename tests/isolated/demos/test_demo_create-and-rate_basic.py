import logging
import time
from collections import ChainMap

import pytest
from dallinger import db
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from psynet.experiment import get_experiment
from psynet.pytest_psynet import (
    bot_class,
    click_finish_button,
    next_page,
    path_to_demo_experiment,
)
from psynet.trial.main import Trial, TrialNode

logger = logging.getLogger(__file__)
PYTEST_BOT_CLASS = bot_class()
EXPERIMENT = None


class TestExp:
    @staticmethod
    def wait_for_element(driver, identifier, by=By.ID, timeout=120):
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, identifier))
        )

    @staticmethod
    def networks_full(bool_value):
        exp = get_experiment()
        for network in exp.networks():
            network.full = bool_value
        db.session.commit()

    def stop_recruiting(self):
        self.networks_full(True)
        print("Stop recruiting")

    @staticmethod
    def make_decision(driver):
        raise NotImplementedError()

    def process_demo(self, bot_recruits, nth_child, stop_at_participant_idx):
        n_creation = 1
        for participant_idx, bot in enumerate(bot_recruits):
            driver = bot.driver
            next_page(
                driver,
                f".push-button-container button:nth-child({nth_child})",
                by=By.CSS_SELECTOR,
            )

            self.wait_for_element(driver, "prompt-image")
            text_input = driver.find_elements(By.ID, "text-input")
            if len(text_input) > 0:
                letter = chr(ord("@") + n_creation)
                driver.find_element(By.ID, "text-input").send_keys(f"test{letter}")
                self.wait_for_element(driver, "next-button")
                next_page(driver, "next-button")
                n_creation += 1
            else:
                self.make_decision(driver)
            if participant_idx == stop_at_participant_idx:
                self.stop_recruiting()
                time.sleep(1)
            self.wait_for_element(driver, "Finish")
            click_finish_button(driver)

        self.assertions()

    def get_nodes_and_trials(self, expected_trial_order):
        nodes = TrialNode.query.order_by(TrialNode.id).all()
        assert len(nodes) == 4, f"Expected 4 nodes, got {len(nodes)}"
        node = nodes[-1]
        trials = Trial.query.order_by(Trial.id).all()
        assert [f"{trial}" for trial in trials] == expected_trial_order
        return nodes, node, trials

    def assertions(self):
        raise NotImplementedError()


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_experiment("create_and_rate/basic")],
    indirect=True,
)
class TestCreateAndRateBasic(TestExp):
    @staticmethod
    def make_decision(driver):
        if driver.find_element(By.CSS_SELECTOR, "#prompt-text strong").text == "testA":
            next_page(
                driver, ".push-button-container button:nth-child(5)", by=By.CSS_SELECTOR
            )
        else:
            next_page(
                driver, ".push-button-container button:nth-child(1)", by=By.CSS_SELECTOR
            )

    def assertions(self):
        expected_trial_order = [
            "Trial-1-CreateTrial",
            "Trial-2-SingleRateTrial",
            "Trial-3-SingleRateTrial",
        ]
        nodes, node, trials = self.get_nodes_and_trials(expected_trial_order)
        rate_trials = trials[1:]
        for trial in rate_trials:
            assert trial.network_id == trials[0].network_id, (
                "Trials should be in the same network"
            )
            assert len(trial.targets) == 1, "Trials should have 1 target"
        ratings = dict(ChainMap(*[trial.answer for trial in rate_trials]))
        assert trials[0].answer == "testA", "First trial should have answer 'testA'"
        assert f"{trials[0]}" == "Trial-1-CreateTrial", (
            "First trial should be 'Trial-1-CreateTrial'"
        )
        assert ratings == {
            "Trial-1-CreateTrial": 5,
            "Node-1-CreateAndRateNode": 1,
        }, (
            "The first creation should get the highest rating, the initial creation should get the lowest rating"
        )
        assert node.definition == trials[0], (
            "Therefore, the aggregated node should point to the first trial (which got the highest rating)"
        )

    def test_demo(self, bot_recruits, db_session):
        self.process_demo(bot_recruits, nth_child=1, stop_at_participant_idx=2)


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_experiment("create_and_rate/basic")],
    indirect=True,
)
class TestCreateAndSelectBasic(TestExp):
    @staticmethod
    def make_decision(driver):
        next_page(driver, "Trial-1-CreateTrial")

    def assertions(self):
        expected_trial_order = [
            "Trial-1-CreateTrial",
            "Trial-2-CreateTrial",
            "Trial-3-SelectTrial",
            "Trial-4-SelectTrial",
            "Trial-5-SelectTrial",
        ]
        nodes, node, trials = self.get_nodes_and_trials(expected_trial_order)

        select_trials = trials[2:]
        for trial in select_trials:
            assert trial.network_id == trials[0].network_id, (
                "Trials should be in the same network"
            )
            assert len(trial.targets) == 3, "Trials should have 3 targets"

        assert trials[0].answer == "testA", "First trial should have answer 'testA'"
        assert trials[1].answer == "testB", "Second trial should have answer 'testB'"
        assert all(trial.answer == "Trial-1-CreateTrial" for trial in select_trials), (
            "All select trials should have answer 'Trial-1-CreateTrial'"
        )
        assert f"{trials[0]}" == "Trial-1-CreateTrial", (
            "First trial should be 'Trial-1-CreateTrial'"
        )
        assert node.definition == trials[0], (
            "Therefore, the aggregated node should point to the first trial (which was always selected)"
        )

    def test_demo(self, bot_recruits, db_session):
        self.process_demo(bot_recruits, nth_child=3, stop_at_participant_idx=4)
