import logging
import tempfile
import time

import pytest
from click import Context

from psynet.bot import BotDriver
from psynet.command_line import export__local, prepare
from psynet.pytest_psynet import bot_class, path_to_test_experiment

logger = logging.getLogger(__file__)
PYTEST_BOT_CLASS = bot_class()
EXPERIMENT = None


@pytest.fixture(scope="session")
def data_root_dir():
    with tempfile.TemporaryDirectory() as tempdir:
        yield tempdir


@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static_big")], indirect=True
)
class TestPrepare:
    def test_prepare(self, deployment_info):
        ctx = Context(prepare)
        ctx.invoke(prepare)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static_big")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
@pytest.mark.dependency()
class TestExpWithExport:
    def test_exp_with_export(
        self,
        data_root_dir,
    ):
        time.sleep(1)
        for _ in range(4):
            bot = BotDriver()
            bot.take_experiment()

        time_started = time.monotonic()

        ctx = Context(export__local)
        ctx.invoke(export__local, path=data_root_dir, n_parallel=None)

        time_finished = time.monotonic()
        time_taken = time_finished - time_started

        # Normally this happens much faster but sometimes it happens slowly on CI
        assert time_taken < 15
