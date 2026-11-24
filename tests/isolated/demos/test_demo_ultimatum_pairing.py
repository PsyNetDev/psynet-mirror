"""Tests for the ultimatum_pairing demo's results text."""

import sys
from types import SimpleNamespace

import pytest

from psynet.experiment import get_experiment
from psynet.pytest_psynet import path_to_demo_experiment

pytestmark = pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_experiment("ultimatum_pairing")],
    indirect=True,
)


@pytest.mark.parametrize(
    "result, answer, expected",
    [
        ("timed_out", None, "own_time_out"),
        ("timed_out", 3, "timed_out"),
        ("partner_left", 3, "partner_left"),
        ("accepted", 3, "accepted"),
    ],
)
def test_every_round_outcome_has_a_results_text(
    in_experiment_directory, result, answer, expected
):
    demo = sys.modules[type(get_experiment()).__module__]
    trial = SimpleNamespace(
        group_round=SimpleNamespace(var=SimpleNamespace(result=result)),
        answer=answer,
    )
    key = demo.OfferTrial.outcome(trial)
    assert key == expected
    assert key in demo.OUTCOME_TEXTS
