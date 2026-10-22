import signal
from unittest.mock import patch

import pytest

from psynet.experiment import Experiment, handle_shutdown_signal


def test_clock_stopped_before_its_config_loads_exits_without_recording(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dallinger_heroku_clock"])
    monkeypatch.setattr("dallinger.config.config", None)

    with (
        patch.object(Experiment, "record_experiment_status") as record,
        pytest.raises(SystemExit) as stopped,
    ):
        handle_shutdown_signal(signal.SIGINT, None)

    assert stopped.value.code == 0
    record.assert_not_called()
