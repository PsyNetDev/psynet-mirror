import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from dallinger import db
from sqlalchemy import text
from sqlalchemy.orm import Session

from psynet import timeline_hold
from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import Clock, GroupBarrier, Regrouper, SimpleGrouper
from psynet.timeline import Timeline

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from test_sync import (  # noqa: E402
    _arrive_at_group_barrier,
    _commit_barrier_arrivals,
)
from timeline_hold_helpers import _json_timeline, _working_participants  # noqa: E402

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
    _backdate_arrivals(pairs, present, 31)

    released = pairs.choose_who_to_release(present)

    assert len(released) == 2
    assert (
        released[0].active_sync_groups["pair"]
        is (released[1].active_sync_groups["pair"])
    )
    (odd_one_out,) = [p for p in present if p not in released]
    assert "pair" not in odd_one_out.active_sync_groups


@in_consents_experiment
def test_clock_regrouper_splits_everyone_waiting_into_balanced_rooms(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    rooms = Regrouper("room", group_size=3, deadline=Clock(45))
    participants = _working_participants(exp, 6)
    _arrive(exp, rooms, participants)
    assert not rooms.would_release(participants)
    assert rooms.expected_release_time(participants[0]) > time.time()

    # One player waited through a tick alone; a newcomer doesn't start a round early.
    _backdate_arrivals(rooms, participants[:1], 60)
    assert not rooms.would_release(participants)
    assert rooms.expected_release_time(participants[0]) > time.time()

    # The last player arrived after the tick, so waits for the next one.
    _backdate_arrivals(rooms, participants[1:5], 60)
    # A tick that is due but not yet split counts down to zero, not to the next tick.
    assert rooms.expected_release_time(participants[0]) <= time.time()
    released = rooms.choose_who_to_release(participants)

    assert participants[5] not in released
    sizes = sorted(len(g.participants) for g in {p.sync_group for p in released})
    assert sizes == [2, 3]


def _put_first_member_in_two_groups(members, **_):
    return [members, members[:1]]


@in_consents_experiment
def test_regrouper_countdown_and_form_groups_check_use_the_whole_pool(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    pairs = Regrouper(
        "pair",
        group_size=2,
        deadline=30,
        form_groups=_put_first_member_in_two_groups,
    )
    first, later = _working_participants(exp, 2)
    _arrive(exp, pairs, [first])
    _backdate_arrivals(pairs, [first], 20)
    _arrive(exp, pairs, [later])

    assert pairs.expected_release_time(later) == pytest.approx(
        pairs.expected_release_time(first)
    )
    _backdate_arrivals(pairs, [first], 20)
    with pytest.raises(ValueError, match="two groups"):
        pairs.choose_who_to_release([first, later])


@in_consents_experiment
def test_simple_grouper_starts_a_short_group_after_waiting(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    published = []
    monkeypatch.setattr(timeline_hold, "_publish_wakes", published.extend)
    grouper = SimpleGrouper(
        "lobby",
        initial_group_size=4,
        min_group_size=2,
        start_short_after=10,
        content="Starting in {SECONDS} s",
    )
    participants = _working_participants(exp, 2)
    _arrive(exp, grouper, participants[:1])
    assert grouper.expected_release_time(participants[0]) is None
    _arrive(exp, grouper, participants[1:])
    assert not grouper.ready_to_group(participants)
    assert grouper.expected_release_time(participants[0]) == pytest.approx(
        time.time() + 10, abs=2
    )
    assert "data-release-in-ms" in grouper.waiting_logic.overlay_html(participants[0])
    countdowns = [w for w in published if w["reason"] == "countdown"]
    assert {w["participant_id"] for w in countdowns} == {p.id for p in participants}

    _backdate_arrivals(grouper, participants, 11)
    released = grouper.choose_who_to_release(participants)

    assert set(released) == set(participants)
    db_session.commit()
    assert participants[0].sync_group.initial_group_size == 2


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"min_group_size": 2, "start_short_after": 60}],
    ids=["no smaller group", "failed before a short start"],
)
def test_simple_grouper_checks_start_short_after(kwargs):
    with pytest.raises(ValueError, match="start_short_after"):
        SimpleGrouper(
            "lobby", initial_group_size=4, **{"start_short_after": 10, **kwargs}
        )


def _count_releases(**kwargs):
    _count_releases.calls += 1


@in_consents_experiment
def test_regrouper_deadline_counts_from_the_first_return_after_a_long_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    team_grouper = SimpleGrouper("team", initial_group_size=3)
    pairs = Regrouper(
        "pair",
        within="team",
        group_size=2,
        deadline=15,
        release_left_over=True,
        on_release=_count_releases,
    )
    team = _working_participants(exp, 3)
    _arrive(exp, team_grouper, team)
    _count_releases.calls = 0
    _arrive(exp, pairs, team)
    assert _count_releases.calls == 1

    # The round took longer than the deadline; the first player back waits.
    team_group = team[0].active_sync_groups["team"]
    team_group.var.set(pairs._state_key, team_group.var.get(pairs._state_key) - 40)
    _arrive(exp, pairs, team[:1])
    assert _waiting(pairs, team[:1]) == team[:1]

    # Alone at the deadline, they sit out without that counting as a split.
    _backdate_arrivals(pairs, team[:1], 16)
    assert pairs.choose_who_to_release(team[:1]) == team[:1]
    assert _count_releases.calls == 1


@in_consents_experiment
def test_group_barrier_can_let_ungrouped_participants_through(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original = exp.timeline
    exp.timeline = Timeline(
        GroupBarrier("round_end", group_type="pair", skip_if_not_in_group=True),
        ModularPage("after", "Round over", time_estimate=1),
    )
    try:
        (participant,) = _working_participants(exp, 1)
        _json_timeline(exp, participant)
        assert exp.timeline.get_current_elt(exp, participant).label == "after"
    finally:
        exp.timeline = original


@in_consents_experiment
def test_a_busy_player_does_not_hold_up_other_teams(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    team_grouper = SimpleGrouper("team", initial_group_size=2)
    team_a, team_b = _working_participants(exp, 2), _working_participants(exp, 2)
    _arrive(exp, team_grouper, team_a)
    _arrive(exp, team_grouper, team_b)
    pairs = Regrouper("pair", within="team", group_size=2, deadline=30)
    _arrive(exp, pairs, team_a[:1])

    with Session(bind=db.engine) as busy_request:
        busy_request.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": team_a[0].id},
        )
        _arrive(exp, pairs, team_b)

    assert _waiting(pairs, team_b) == []
