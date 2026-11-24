"""Tests for the ultimatum_pairing demo's results text."""

import sys
from types import SimpleNamespace

import pytest

from psynet.experiment import get_experiment
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.timeline import CodeBlock

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
    groups = {}
    cohort = SimpleNamespace(
        n_active_participants=cohort_size,
        remove_participant=lambda participant, reason: groups.clear(),
    )
    groups[demo.COHORT] = cohort
    player = SimpleNamespace(
        in_sync_group=lambda group_type: False,
        sync_group_removal_reason=lambda group_type: None,
        active_sync_groups=groups,
        var=SimpleNamespace(),
    )
    assert demo.round_status(player) == round_status
    # Run the timeline's steps that save the reason and leave the cohort, in
    # their order: leaving first would make every player look alone.
    steps = [
        elt
        for elt in get_experiment().timeline.elts["main"]
        if isinstance(elt, CodeBlock)
        and elt.function.__name__ in ("save_game_over_reason", "_leave")
    ]
    assert len(steps) == 2
    for step in steps:
        step.function(player)
    assert player.var.game_over_reason == game_over_reason


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
