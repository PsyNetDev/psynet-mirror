import sys
from datetime import timedelta
from pathlib import Path

import pytest

from psynet.experiment import get_experiment
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import Clock, Regrouper, SimpleGrouper

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from test_sync import (  # noqa: E402
    _arrive_at_group_barrier,
    _commit_barrier_arrivals,
)
from timeline_hold_helpers import _working_participants  # noqa: E402

in_consents_experiment = pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)


def _arrive(exp, barrier, participants):
    for participant in participants:
        _arrive_at_group_barrier(exp, barrier, participant)
    _commit_barrier_arrivals()


def _waiting(barrier, participants):
    return [p for p in participants if barrier._participant_is_waiting(p)]


def _backdate_arrivals(barrier, participants, seconds):
    for participant in participants:
        participant.active_barriers[barrier.id].arrival_time -= timedelta(
            seconds=seconds
        )


@in_consents_experiment
def test_regrouper_pairs_within_teams_and_does_not_wait_for_absent_members(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    team_grouper = SimpleGrouper("team", initial_group_size=4)
    pairs = Regrouper(
        "pair",
        within="team",
        group_size=2,
        deadline=30,
        content="Next round in {SECONDS} s",
    )
    team = _working_participants(exp, 4)
    _arrive(exp, team_grouper, team)

    _arrive(exp, pairs, team[:3])
    assert _waiting(pairs, team[:3]) == team[:3]
    assert "psynet-timeline-hold-countdown" in pairs.waiting_logic.overlay_html(team[0])

    _arrive(exp, pairs, team[3:])
    assert _waiting(pairs, team) == []
    round_1 = {frozenset(p.active_sync_groups["pair"].participants) for p in team}
    assert len(round_1) == 2
    assert all(len(pair) == 2 for pair in round_1)

    # Next round: one member is absent, so the others go ahead at the deadline
    # and the odd one out keeps waiting for the round after.
    present = team[:3]
    _arrive(exp, pairs, present)
    assert all("pair" not in p.active_sync_groups for p in present)
    assert _waiting(pairs, present) == present
    team_group = team[0].active_sync_groups["team"]
    key = pairs._state_key
    team_group.var.set(key, team_group.var.get(key) - 31)

    released = pairs.choose_who_to_release(present)

    assert len(released) == 2
    assert (
        released[0].active_sync_groups["pair"]
        is (released[1].active_sync_groups["pair"])
    )


@in_consents_experiment
def test_clock_regrouper_splits_everyone_waiting_into_balanced_rooms(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    rooms = Regrouper("room", group_size=3, deadline=Clock(45))
    participants = _working_participants(exp, 5)
    _arrive(exp, rooms, participants)
    assert not rooms.would_release(participants)

    # One player waited through a tick alone; a newcomer doesn't start a round early.
    _backdate_arrivals(rooms, participants[:1], 60)
    assert not rooms.would_release(participants)

    _backdate_arrivals(rooms, participants[1:], 60)
    released = rooms.choose_who_to_release(participants)

    sizes = sorted(len(g.participants) for g in {p.sync_group for p in released})
    assert sizes == [2, 3]


@in_consents_experiment
def test_simple_grouper_starts_a_short_group_after_waiting(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper = SimpleGrouper(
        "lobby", initial_group_size=4, min_group_size=2, start_short_after=10
    )
    participants = _working_participants(exp, 2)
    _arrive(exp, grouper, participants)
    assert not grouper.ready_to_group(participants)

    _backdate_arrivals(grouper, participants, 11)
    released = grouper.choose_who_to_release(participants)

    assert set(released) == set(participants)
    assert participants[0].sync_group.initial_group_size == 2


def test_simple_grouper_start_short_after_needs_a_smaller_min_group_size():
    with pytest.raises(ValueError, match="start_short_after"):
        SimpleGrouper("lobby", initial_group_size=4, start_short_after=10)
