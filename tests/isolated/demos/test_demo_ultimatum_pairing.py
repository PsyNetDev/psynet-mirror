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
    "cohort_size, round_status, game_over_reason",
    [(3, "sat_out", "sat_out_too_often"), (1, "no_cohort", "too_few_players")],
)
def test_a_player_left_alone_ends_rather_than_sitting_out(
    in_experiment_directory, monkeypatch, cohort_size, round_status, game_over_reason
):
    demo = sys.modules[type(get_experiment()).__module__]
    monkeypatch.setattr(demo.pairing, "sat_out", lambda participant: True)
    monkeypatch.setattr(demo.pairing, "rounds_played", lambda participant: 0)
    monkeypatch.setattr(
        demo.pairing, "rounds_sat_out", lambda participant: demo.MAX_SIT_OUTS
    )
    cohort = SimpleNamespace(n_active_participants=cohort_size)
    player = SimpleNamespace(
        in_sync_group=lambda group_type: False,
        sync_group_removal_reason=lambda group_type: None,
        active_sync_groups={demo.COHORT: cohort},
    )
    assert demo.round_status(player) == round_status
    assert demo.game_over_reason(player) == game_over_reason


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
