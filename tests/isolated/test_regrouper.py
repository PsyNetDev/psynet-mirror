import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from dallinger import db
from sqlalchemy import text
from sqlalchemy.orm import Session

from psynet import sync, timeline_hold
from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    Clock,
    GroupBarrier,
    Regrouper,
    SimpleGrouper,
    _latest_tick,
)
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
        content="Next round (<1 min) in {SECONDS} s",
    )
    team = _working_participants(exp, 4)
    _arrive(exp, team_grouper, team)

    _arrive(exp, pairs, team[:3])
    assert _waiting(pairs, team[:3]) == team[:3]
    html = pairs.waiting_logic.overlay_html(team[0])
    assert "psynet-timeline-hold-countdown" in html and "(&lt;1 min)" in html

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
    assert rooms.expected_release_time(participants[5]) > time.time()
    released = rooms.choose_who_to_release(participants)

    assert participants[5] not in released
    sizes = sorted(len(g.participants) for g in {p.sync_group for p in released})
    assert sizes == [2, 3]


@in_consents_experiment
def test_regrouper_countdown_after_a_concurrent_release(
    in_experiment_directory, db_session, monkeypatch
):
    """Another request can put a waiter into a group while their countdown is drawn."""
    exp = get_experiment()
    rooms = Regrouper("room", group_size=3, deadline=30, release_left_over=True)
    participants = _working_participants(exp, 2)
    _arrive(exp, rooms, participants)
    populate = sync._populate_active_barriers

    def release_first_then_populate(waiters):
        db.session.execute(
            text(
                "UPDATE participant_link_barrier SET released = true"
                " WHERE participant_id = :id"
            ),
            {"id": participants[0].id},
        )
        populate(waiters)

    monkeypatch.setattr(sync, "_populate_active_barriers", release_first_then_populate)
    assert rooms.expected_release_time(participants[0]) is None


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
    assert pairs.expected_release_time(first) is None
    _backdate_arrivals(pairs, [first], 20)
    _arrive(exp, pairs, [later])

    assert pairs.expected_release_time(later) == pytest.approx(
        pairs.expected_release_time(first)
    )
    _backdate_arrivals(pairs, [first], 20)
    with pytest.raises(ValueError, match="two groups"):
        pairs.choose_who_to_release([first, later])


def _lobby_message(seconds_left):
    if seconds_left is None:
        return "Waiting for another player."
    return "Starting in {SECONDS} s"


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
        content=_lobby_message,
    )
    participants = _working_participants(exp, 2)
    _arrive(exp, grouper, participants[:1])
    assert grouper.expected_release_time(participants[0]) is None
    assert "Waiting for another player." in grouper.waiting_logic.overlay_html(
        participants[0]
    )
    _arrive(exp, grouper, participants[1:])
    assert not grouper.ready_to_group(participants)
    assert grouper.expected_release_time(participants[0]) == pytest.approx(
        time.time() + 10, abs=2
    )
    assert "data-release-in-ms" in grouper.waiting_logic.overlay_html(participants[0])
    countdowns = [w for w in published if w["reason"] == "countdown"]
    assert {w["participant_id"] for w in countdowns} == {p.id for p in participants}
    assert all("Starting in" in w["hold_message"] for w in countdowns)

    _backdate_arrivals(grouper, participants, 11)
    assert 'countdown">0<' in grouper.waiting_logic.overlay_html(participants[0])
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


def _five_minutes(participant):
    return 300


def test_simple_grouper_accepts_callable_max_wait_time_with_start_short_after():
    SimpleGrouper(
        "lobby",
        initial_group_size=4,
        min_group_size=2,
        start_short_after=10,
        max_wait_time=_five_minutes,
    )


def _count_releases(**kwargs):
    _count_releases.calls += 1


@in_consents_experiment
def test_regrouper_left_over_waits_for_teammates_still_in_the_round(
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
    (odd_one_out,) = [p for p in team if "pair" not in p.active_sync_groups]
    paired = [p for p in team if p is not odd_one_out]

    # The pair's round runs past the deadline; the odd one out, back first,
    # keeps waiting for them instead of sitting out again.
    team_group = team[0].active_sync_groups["team"]
    team_group.var.set(pairs._state_key, team_group.var.get(pairs._state_key) - 40)
    _arrive(exp, pairs, [odd_one_out])
    _backdate_arrivals(pairs, [odd_one_out], 16)
    assert pairs.choose_who_to_release([odd_one_out]) == []
    # ...but for one more deadline at most, then they sit out.
    _backdate_arrivals(pairs, [odd_one_out], 15)
    assert pairs.choose_who_to_release([odd_one_out]) == [odd_one_out]
    _backdate_arrivals(pairs, [odd_one_out], -15)

    _arrive(exp, pairs, paired)
    assert _waiting(pairs, team) == []
    assert _count_releases.calls == 2
    # Leaving their pair for the next round counts as moving on, not dropping out.
    assert "moved_on" in [
        link.removal_reason
        for link in paired[0].sync_group_links
        if link.sync_group.group_type == "pair"
    ]


@in_consents_experiment
def test_clock_regrouper_left_over_waits_one_more_tick(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    team_grouper = SimpleGrouper("team", initial_group_size=3)
    pairs = Regrouper(
        "pair", within="team", group_size=2, deadline=Clock(15), release_left_over=True
    )
    team = _working_participants(exp, 3)
    _arrive(exp, team_grouper, team)
    # Two were waiting at the last tick, so they pair up when the third arrives.
    _arrive(exp, pairs, team[:2])
    _backdate_arrivals(pairs, team[:2], 16)
    _arrive(exp, pairs, team[2:])
    assert _waiting(pairs, team) == team[2:]
    team_group = team[0].active_sync_groups["team"]
    team_group.var.set(pairs._state_key, team_group.var.get(pairs._state_key) - 32)

    # The pair is still playing: held through one tick, released at the next.
    since_tick = time.time() - _latest_tick(time.time(), 15)
    _backdate_arrivals(pairs, team[2:], since_tick + 1)
    assert pairs.choose_who_to_release(team[2:]) == []
    _backdate_arrivals(pairs, team[2:], 15)
    assert pairs.choose_who_to_release(team[2:]) == team[2:]


def test_regrouper_max_wait_time_outlasts_a_lone_wait():
    with pytest.raises(ValueError, match="twice the deadline"):
        Regrouper(
            "pair",
            within="team",
            group_size=2,
            deadline=150,
            release_left_over=True,
        )


@in_consents_experiment
def test_group_barrier_can_let_ungrouped_participants_through(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original = exp.timeline
    exp.timeline = Timeline(
        # A barrier that kicks late members lets ungrouped participants through.
        GroupBarrier(
            "round_end", group_type="pair", timeout_between_barriers_action="kick"
        ),
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


def _team_and_pairs(exp, n, **kwargs):
    team_grouper = SimpleGrouper("team", initial_group_size=n, min_group_size=2)
    pairs = Regrouper(
        "pair",
        within="team",
        group_size=2,
        roles=["proposer", "responder"],
        release_left_over=True,
        deadline=30,
        **kwargs,
    )
    team = _working_participants(exp, n)
    _arrive(exp, team_grouper, team)
    return team, pairs


def _partner(participant):
    (partner,) = [
        p
        for p in participant.active_sync_groups["pair"].participants
        if p is not participant
    ]
    return partner


@in_consents_experiment
def test_regrouper_alternates_roles_and_partners_and_counts_rounds(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    team, pairs = _team_and_pairs(exp, 4)

    _arrive(exp, pairs, team)
    first = {p.id: (pairs.role(p), _partner(p)) for p in team}
    assert (
        sorted(role for role, _ in first.values())
        == ["proposer"] * 2 + ["responder"] * 2
    )
    assert all(pairs.role(_partner(p)) != pairs.role(p) for p in team)

    _arrive(exp, pairs, team)
    for p in team:
        role, partner = first[p.id]
        assert pairs.role(p) != role
        assert _partner(p) is not partner
        assert pairs.rounds_played(p) == 2

    # Three players left: one sits out, and plays first next round.
    team[0].active_sync_groups["team"].remove_participant(team[3])
    _arrive(exp, pairs, team[:3])
    (sitter,) = [p for p in team[:3] if "pair" not in p.active_sync_groups]
    assert pairs.role(sitter) is None
    assert pairs.rounds_sat_out(sitter) == 1
    _arrive(exp, pairs, team[:3])
    assert "pair" in sitter.active_sync_groups


@in_consents_experiment
def test_regrouper_keep_roles_balances_newcomers(in_experiment_directory, db_session):
    exp = get_experiment()
    team, pairs = _team_and_pairs(exp, 3, keep_roles=True)

    _arrive(exp, pairs, team)
    (sitter,) = [p for p in team if "pair" not in p.active_sync_groups]
    playing = [p for p in team if p is not sitter]
    assert {pairs.role(p) for p in playing} == {"proposer", "responder"}
    roles = {p.id: pairs.role(p) for p in team}

    (newcomer,) = _working_participants(exp, 1)
    team[0].active_sync_groups["team"].add_participant(newcomer)
    _arrive(exp, pairs, team + [newcomer])
    assert {p.id: pairs.role(p) for p in team} == roles
    assert pairs.role(newcomer) != pairs.role(sitter)
    assert all("pair" in p.active_sync_groups for p in team + [newcomer])
    assert pairs.rounds_played(sitter) == 1
