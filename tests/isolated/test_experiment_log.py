import logging
from types import SimpleNamespace

import pytest

from psynet.experiment import Experiment


@pytest.mark.parametrize(
    "key, expected",
    [("-----", "Participant 2 finished."), ("NOTE", "NOTE Participant 2 finished.")],
)
def test_log_leaves_out_keys_without_letters_or_digits(caplog, key, expected):
    with caplog.at_level(logging.INFO):
        Experiment.log(SimpleNamespace(verbose=True), "Participant 2 finished.", key)
    assert caplog.messages == [expected]
