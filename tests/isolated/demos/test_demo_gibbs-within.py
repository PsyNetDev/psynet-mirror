import logging
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from psynet.pytest_psynet import (
    bot_class,
    click_finish_button,
    next_page,
    path_to_demo_experiment,
)
from psynet.trial.gibbs import GibbsNetwork, GibbsNode

logger = logging.getLogger(__file__)
PYTEST_BOT_CLASS = bot_class()
EXPERIMENT = None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("gibbs_within")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_exp(self, bot_recruits, db_session):
        for participant, bot in enumerate(bot_recruits):
            driver = bot.driver
            time.sleep(1)
            n_trials = 4
            for i in range(n_trials):
                WebDriverWait(driver, 60).until(
                    EC.element_to_be_clickable((By.ID, "next-button"))
                )
                next_page(driver, "next-button")

            dimension_order = GibbsNetwork.query.one().dimension_order
            nodes = GibbsNode.query.order_by(GibbsNode.id).all()
            assert len(set([node.initial_index for node in nodes])) == 1, (
                "All nodes should have same initial index."
            )
            initial_index = nodes[0].initial_index
            n_nodes = n_trials + 1
            assert len(nodes) == n_nodes, (
                "There should be one node per trial plus one for the initial node."
            )
            dimension_start_index = dimension_order.index(initial_index)

            predicted_dimension_order = (dimension_order * 3)[
                dimension_start_index : (dimension_start_index + n_nodes)
            ]
            real_dimension_order = [node.active_index for node in nodes]
            assert real_dimension_order == predicted_dimension_order, (
                "Dimensions are not visited in correct order."
            )

            next_page(driver, "next-button")
            click_finish_button(driver)
