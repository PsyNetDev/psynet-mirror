import signal
from unittest.mock import Mock, patch

import pytest

from psynet.experiment import Experiment, handle_shutdown_signal


@pytest.mark.parametrize(
    "config, recorded",
    [(None, False), (Mock(ready=False), False), (Mock(ready=True), True)],
)
def test_clock_records_going_offline_only_once_its_config_has_loaded(
    monkeypatch, config, recorded
):
    monkeypatch.setattr("sys.argv", ["dallinger_heroku_clock"])
    monkeypatch.setattr("dallinger.config.config", config)

    with (
        patch.object(Experiment, "record_experiment_status") as record,
        patch.object(Experiment, "notifier"),
        pytest.raises(SystemExit) as stopped,
    ):
        handle_shutdown_signal(signal.SIGINT, None)

    assert stopped.value.code == 0
    assert record.called is recorded
