import sys
import time
from pathlib import Path

import pytest
from dallinger import db
from dallinger.models import timenow
from sqlalchemy import text
from sqlalchemy.orm import Session

from psynet import sync, timeline_hold
from psynet.bot import _backdate_arrivals, _backdate_last_split
from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    GroupBarrier,
    ParticipantLinkSyncGroup,
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


@in_consents_experiment
def test_regrouper_pairs_within_cohorts_and_does_not_wait_for_absent_members(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=4)
    pairs = Regrouper(
        "pair",
        within="cohort",
        group_size=2,
        deadline=30,
        waiting_message="Next round (<1 min) in {SECONDS} s",
    )
    cohort = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, cohort)

    _arrive(exp, pairs, cohort[:3])
    assert _waiting(pairs, cohort[:3]) == cohort[:3]
    html = pairs.waiting_logic.overlay_html(cohort[0])
    assert "psynet-timeline-hold-countdown" in html and "(&lt;1 min)" in html

    _arrive(exp, pairs, cohort[3:])
    assert _waiting(pairs, cohort) == []
    round_1 = {frozenset(p.active_sync_groups["pair"].participants) for p in cohort}
    assert len(round_1) == 2
    assert all(len(pair) == 2 for pair in round_1)

    # Next round: one member is absent, so the others go ahead at the deadline
    # and the odd one out keeps waiting for the round after.
    present = cohort[:3]
    _arrive(exp, pairs, present)
    assert all("pair" not in p.active_sync_groups for p in present)
    assert _waiting(pairs, present) == present
    _backdate_last_split(pairs, cohort[0].active_sync_groups["cohort"], 31)
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
def test_regrouper_waits_for_a_late_member_until_they_leave_the_within_group(
    in_experiment_directory, db_session
):
    """A member removed late from their pair holds up the next split while still in the cohort."""
    exp = get_experiment()
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=4, quorum=2)
    pairs = Regrouper("pair", within="cohort", group_size=2, deadline=30)
    cohort = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, cohort)
    _arrive(exp, pairs, cohort)
    late, present = cohort[3], cohort[:3]
    late.active_sync_groups["pair"].remove_participant(late, reason="late")

    _arrive(exp, pairs, present)
    assert _waiting(pairs, present) == present

    late.active_sync_groups["cohort"].remove_participant(late, reason="late")
    assert len(pairs.choose_who_to_release(present)) == 2


@in_consents_experiment
def test_regrouper_can_avoid_everyone_met_before(in_experiment_directory, db_session):
    exp = get_experiment()
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=4)
    pairs = Regrouper("pair", within="cohort", group_size=2, avoid_repeats="all_rounds")
    cohort = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, cohort)

    met = set()
    for _ in range(3):
        _arrive(exp, pairs, cohort)
        met |= {
            frozenset(p.id for p in member.active_sync_groups["pair"].participants)
            for member in cohort
        }
    # Three rounds of pairs meet all six partnerships of a cohort of four.
    assert len(met) == 6


@in_consents_experiment
def test_every_regrouper_splits_everyone_waiting_into_balanced_rooms(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    rooms = Regrouper("room", group_size=3, every=45)
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
    rooms = Regrouper("room", group_size=3, deadline=30, left_over="sit_out")
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


@in_consents_experiment
def test_regrouper_cohorts_have_their_own_deadlines(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=3)
    pairs = Regrouper("pair", within="cohort", group_size=2, deadline=30)
    cohorts = [_working_participants(exp, 3) for _ in range(2)]
    for cohort in cohorts:
        _arrive(exp, cohort_grouper, cohort)

    # A split in one cohort does not restart the other cohort's deadline.
    for cohort in cohorts:
        _arrive(exp, pairs, cohort[:2])
        _backdate_arrivals(pairs, cohort[:2], 31)
        assert len(pairs.choose_who_to_release(cohort[:2])) == 2


def _lobby_message(seconds_left):
    if seconds_left is None:
        return "Waiting for another player."
    return "Starting in {SECONDS} s"


@pytest.mark.parametrize(
    "waiting_message, lone_text",
    [
        (_lobby_message, "Waiting for another player."),
        ("Starting in {SECONDS} s", "Waiting for other participants…"),
    ],
)
@in_consents_experiment
def test_simple_grouper_starts_a_short_group_after_waiting(
    in_experiment_directory, db_session, monkeypatch, waiting_message, lone_text
):
    exp = get_experiment()
    published = []
    monkeypatch.setattr(timeline_hold, "_publish_wakes", published.extend)
    grouper = SimpleGrouper(
        "lobby",
        initial_group_size=4,
        start_short_after=10,
        start_short_with=2,
        waiting_message=waiting_message,
    )
    participants = _working_participants(exp, 2)
    _arrive(exp, grouper, participants[:1])
    assert grouper.expected_release_time(participants[0]) is None
    assert lone_text in grouper.waiting_logic.overlay_html(participants[0])
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
    group = participants[0].sync_group
    assert (group.initial_group_size, group.min_group_size) == (2, 2)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"start_short_after": 10}, "pass quorum"),
        ({"start_short_with": 2}, "only used with start_short_after"),
        ({"start_short_after": 10, "start_short_with": 5}, "start_short_with <="),
        ({"start_short_after": 60, "start_short_with": 2}, "less than max_wait_time"),
        ({"start_short_after": 10, "quorum": 5}, "Lower quorum"),
        (
            {
                "start_short_after": 10,
                "quorum": 5,
                "join_existing_groups": True,
                "max_group_size": 6,
            },
            "Lower quorum",
        ),
    ],
)
def test_simple_grouper_checks_start_short_after(kwargs, message):
    with pytest.raises(ValueError, match=message):
        SimpleGrouper("lobby", initial_group_size=4, **kwargs)


def test_simple_grouper_quorum():
    def lobby(**kwargs):
        return SimpleGrouper("lobby", initial_group_size=4, max_wait_time=120, **kwargs)

    short = {"start_short_after": 60, "start_short_with": 2}
    assert lobby(quorum=3).quorum == 3
    assert lobby(**short).quorum == 2
    assert lobby(quorum=2, start_short_after=60).start_short_with == 2
    assert lobby(quorum=4, start_short_after=60).start_short_with == 4
    with pytest.raises(ValueError, match="at most start_short_with"):
        lobby(quorum=3, **short)
    with pytest.warns(UserWarning, match="Pass quorum"):
        assert lobby().quorum == 4
    with pytest.warns(FutureWarning, match="deprecated"):
        assert lobby(min_group_size=3).quorum == 3
    with pytest.warns(FutureWarning):
        assert lobby(min_group_size=0).quorum == 1
    with pytest.raises(ValueError, match="never reach"):
        lobby(quorum=6, join_existing_groups=True, max_group_size=5)
    with pytest.raises(ValueError, match="not a lambda"):
        lobby(quorum=4, below_quorum=lambda participant, group: "fail")
    with pytest.raises(TypeError, match="below_quorum='continue_without_group'"):
        lobby(quorum=4, fail_participants_below_min_size=False)


def _five_minutes(participant):
    return 300


def test_simple_grouper_accepts_callable_max_wait_time_with_start_short_after():
    SimpleGrouper(
        "lobby",
        initial_group_size=4,
        start_short_after=10,
        start_short_with=2,
        max_wait_time=_five_minutes,
    )


def _count_releases(groups, **kwargs):
    _count_releases.calls += 1
    assert all(group.id is not None for group in groups)


@in_consents_experiment
def test_regrouper_left_over_waits_for_cohort_still_in_the_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=3)
    pairs = Regrouper(
        "pair",
        within="cohort",
        group_size=2,
        deadline=15,
        left_over="sit_out",
        on_release=_count_releases,
    )
    cohort = _working_participants(exp, 3)
    _arrive(exp, cohort_grouper, cohort)
    _count_releases.calls = 0
    _arrive(exp, pairs, cohort)
    assert _count_releases.calls == 1
    (odd_one_out,) = [p for p in cohort if "pair" not in p.active_sync_groups]
    paired = [p for p in cohort if p is not odd_one_out]
    # Sitting out the first round: never in a pair, so no removal reason.
    assert pairs.sat_out(odd_one_out)
    assert odd_one_out.sync_group_removal_reason("pair") is None

    # The pair's round runs past the deadline; the odd one out, back first,
    # keeps waiting for them instead of sitting out again.
    _backdate_last_split(pairs, cohort[0].active_sync_groups["cohort"], 40)
    _arrive(exp, pairs, [odd_one_out])
    _backdate_arrivals(pairs, [odd_one_out], 16)
    assert pairs.choose_who_to_release([odd_one_out]) == []
    # ...but for one more deadline at most, then they sit out.
    _backdate_arrivals(pairs, [odd_one_out], 15)
    assert pairs.choose_who_to_release([odd_one_out]) == [odd_one_out]
    _backdate_arrivals(pairs, [odd_one_out], -15)

    _arrive(exp, pairs, paired)
    assert _waiting(pairs, cohort) == []
    assert _count_releases.calls == 2
    # Leaving their pair for the next round counts as moving on, not dropping out.
    assert "moved_on" in [
        link.removal_reason
        for link in paired[0].sync_group_links
        if link.sync_group.group_type == "pair"
    ]


@in_consents_experiment
def test_every_regrouper_left_over_waits_one_more_tick(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=3)
    pairs = Regrouper(
        "pair",
        within="cohort",
        group_size=2,
        every=15,
        left_over="sit_out",
    )
    cohort = _working_participants(exp, 3)
    _arrive(exp, cohort_grouper, cohort)
    # Two were waiting at the last tick, so they pair up when the third arrives.
    _arrive(exp, pairs, cohort[:2])
    _backdate_arrivals(pairs, cohort[:2], 16)
    _arrive(exp, pairs, cohort[2:])
    assert _waiting(pairs, cohort) == cohort[2:]
    _backdate_last_split(pairs, cohort[0].active_sync_groups["cohort"], 32)

    # The pair is still playing: held through one tick, released at the next.
    since_tick = time.time() - _latest_tick(time.time(), 15)
    _backdate_arrivals(pairs, cohort[2:], since_tick + 1)
    assert pairs.choose_who_to_release(cohort[2:]) == []
    _backdate_arrivals(pairs, cohort[2:], 15)
    assert pairs.choose_who_to_release(cohort[2:]) == cohort[2:]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "needs group_size"),
        ({"roles": ["a", "b"], "group_size": 3}, "len\\(roles\\)"),
        ({"group_size": 2, "deadline": 30, "every": 30}, "not both"),
        ({"group_size": 2, "below_quorum": "continue_without_group"}, "never"),
        ({"group_size": 2, "deadline": 0}, "deadline must be positive"),
        ({"group_size": 2, "every": 0}, "every must be positive"),
        *[
            ({"group_size": 2, "stop_top_ups_after_rounds": value}, "whole number")
            for value in (-1, 1.5, "1", True)
        ],
        (
            {"group_size": 2, "within": None, "stop_top_ups_after_rounds": 1},
            "needs within",
        ),
    ],
)
def test_regrouper_checks_its_settings(kwargs, message):
    with pytest.raises((TypeError, ValueError), match=message):
        Regrouper("pair", **{"within": "cohort", **kwargs})


def test_regrouper_max_wait_time_outlasts_a_lone_wait():
    def pairs(**kwargs):
        return Regrouper(
            "pair", within="cohort", group_size=2, left_over="sit_out", **kwargs
        )

    assert pairs(deadline=30).max_wait_time == 300
    assert pairs(every=150).max_wait_time == 360
    with pytest.raises(ValueError, match="twice the deadline"):
        pairs(deadline=150, max_wait_time=300)


@in_consents_experiment
def test_group_barrier_lets_removed_members_through(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original = exp.timeline
    exp.timeline = Timeline(
        GroupBarrier("round_end", group_type="pair"),
        ModularPage("after", "Round over", time_estimate=1),
    )
    try:
        removed, partner = _working_participants(exp, 2)
        _arrive(exp, SimpleGrouper("pair", initial_group_size=2), [removed, partner])
        removed.active_sync_groups["pair"].remove_participant(removed)
        db_session.commit()
        _json_timeline(exp, removed)
        assert exp.timeline.get_current_elt(exp, removed).label == "after"
    finally:
        exp.timeline = original


@in_consents_experiment
def test_a_busy_player_does_not_hold_up_other_cohorts(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=2)
    cohort_a, cohort_b = _working_participants(exp, 2), _working_participants(exp, 2)
    _arrive(exp, cohort_grouper, cohort_a)
    _arrive(exp, cohort_grouper, cohort_b)
    pairs = Regrouper("pair", within="cohort", group_size=2, deadline=30)
    _arrive(exp, pairs, cohort_a[:1])

    with Session(bind=db.engine) as busy_request:
        busy_request.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": cohort_a[0].id},
        )
        _arrive(exp, pairs, cohort_b)

    assert _waiting(pairs, cohort_b) == []


def _cohort_and_pairs(exp, n, **kwargs):
    cohort_grouper = SimpleGrouper("cohort", initial_group_size=n, quorum=2)
    pairs = Regrouper(
        "pair",
        within="cohort",
        roles=["proposer", "responder"],
        left_over="sit_out",
        deadline=30,
        **kwargs,
    )
    cohort = _working_participants(exp, n)
    _arrive(exp, cohort_grouper, cohort)
    return cohort, pairs


@in_consents_experiment
def test_regrouper_keeps_a_sit_out_when_the_sitter_returns_in_the_same_request(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(exp, 3)
    _arrive(exp, pairs, cohort)
    (sitter,) = [p for p in cohort if "pair" not in p.active_sync_groups]
    _arrive_at_group_barrier(exp, pairs, sitter)
    # Sitting out again, then coming straight back, all before the next commit.
    visit = sitter.active_barriers[pairs.id]
    visit.sat_out = True
    visit.release()
    _arrive(exp, pairs, [sitter])
    assert pairs.rounds_sat_out(sitter) == 2


def _pair_same_roles(members, barrier, **_):
    ordered = sorted(members, key=barrier.role)
    return [ordered[:2], ordered[2:]]


def _lowest_id_responds(members, **_):
    responder, proposer = sorted(members, key=lambda p: p.id)
    return [{"responder": responder, "proposer": proposer}]


@in_consents_experiment
def test_regrouper_form_groups_can_return_groups_keyed_by_role(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(exp, 2, form_groups=_lowest_id_responds)
    _arrive(exp, pairs, cohort)
    assert [pairs.role(p) for p in cohort] == ["responder", "proposer"]


@in_consents_experiment
def test_regrouper_keep_roles_needs_one_member_per_role(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(
        exp, 4, keep_roles=True, form_groups=_pair_same_roles
    )
    _arrive(exp, pairs, cohort[:3])
    with pytest.raises(ValueError, match="one member per role"):
        _arrive(exp, pairs, cohort[3:])


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
    cohort, pairs = _cohort_and_pairs(exp, 4)

    _arrive(exp, pairs, cohort)
    first = {p.id: (pairs.role(p), _partner(p)) for p in cohort}
    assert (
        sorted(role for role, _ in first.values())
        == ["proposer"] * 2 + ["responder"] * 2
    )
    assert all(pairs.role(_partner(p)) != pairs.role(p) for p in cohort)

    _arrive(exp, pairs, cohort)
    for p in cohort:
        role, partner = first[p.id]
        assert pairs.role(p) != role
        assert _partner(p) is not partner
        assert pairs.rounds_played(p) == 2
        assert p.sync_group_removal_reason("pair") is None
    # A player removed from their pair, as by a kick, still sees their role.
    role = pairs.role(cohort[0])
    cohort[0].active_sync_groups["pair"].remove_participant(cohort[0])
    assert pairs.role(cohort[0]) == role

    # Three players left: one sits out, and plays first next round.
    cohort[0].active_sync_groups["cohort"].remove_participant(cohort[3])
    _arrive(exp, pairs, cohort[:3])
    (sitter,) = [p for p in cohort[:3] if "pair" not in p.active_sync_groups]
    assert pairs.role(sitter) is None
    assert (pairs.rounds_sat_out(sitter), pairs.sat_out(sitter)) == (1, True)
    # cohort[0] was removed from their pair above, so the regrouper didn't move them on.
    expected_reason = None if sitter is cohort[0] else "moved_on"
    assert sitter.sync_group_removal_reason("pair") == expected_reason
    _arrive(exp, pairs, cohort[:3])
    assert "pair" in sitter.active_sync_groups
    assert not pairs.sat_out(sitter)


@in_consents_experiment
def test_regrouper_keep_roles_balances_newcomers(in_experiment_directory, db_session):
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(exp, 3, keep_roles=True)

    _arrive(exp, pairs, cohort)
    (sitter,) = [p for p in cohort if "pair" not in p.active_sync_groups]
    playing = [p for p in cohort if p is not sitter]
    assert {pairs.role(p) for p in playing} == {"proposer", "responder"}
    # A newcomer who sat out has not played a role yet.
    assert pairs.role(sitter) is None
    roles = {p.id: pairs.role(p) for p in playing}

    (newcomer,) = _working_participants(exp, 1)
    cohort[0].active_sync_groups["cohort"].add_participant(newcomer)
    _arrive(exp, pairs, cohort + [newcomer])
    assert {p.id: pairs.role(p) for p in playing} == roles
    assert pairs.role(newcomer) != pairs.role(sitter)
    assert all("pair" in p.active_sync_groups for p in cohort + [newcomer])
    assert pairs.rounds_played(sitter) == 1


@in_consents_experiment
def test_regrouper_lets_a_player_waiting_alone_carry_on(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    regrouper = Regrouper(
        "room",
        group_size=8,
        smallest_group=2,
        every=10,
        max_wait_time=60,
        max_wait_action="continue_without_group",
    )
    (player,) = _working_participants(exp, 1)
    _arrive(exp, regrouper, [player])
    regrouper.handle_max_wait_timeout(player)
    db_session.commit()

    assert not player.failed
    assert not player.in_sync_group("room")


def _open_cohorts(stop_top_ups_after_rounds):
    cohort_grouper = SimpleGrouper(
        "cohort",
        initial_group_size=2,
        quorum=2,
        max_group_size=4,
        join_existing_groups=True,
    )
    pairs = Regrouper(
        "pair",
        within="cohort",
        group_size=2,
        stop_top_ups_after_rounds=stop_top_ups_after_rounds,
    )
    return cohort_grouper, pairs


@pytest.mark.parametrize("open_for_rounds", [0, 1])
@in_consents_experiment
def test_regrouper_stops_top_ups_after_rounds(
    in_experiment_directory, db_session, open_for_rounds
):
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(open_for_rounds)
    *starters, latecomer, too_late = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, starters)
    cohort = starters[0].active_sync_groups["cohort"]

    _arrive(exp, pairs, starters)
    if open_for_rounds:
        _arrive(exp, cohort_grouper, [latecomer])
        assert latecomer.in_sync_group("cohort")
        _arrive(exp, pairs, [*starters, latecomer])
    assert not cohort.accepts_top_ups
    _arrive(exp, cohort_grouper, [too_late])
    assert not too_late.in_sync_group("cohort")


@in_consents_experiment
def test_closing_split_counts_a_newcomer_who_joined_in_another_request(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(1)
    *starters, newcomer = _working_participants(exp, 3)
    _arrive(exp, cohort_grouper, starters)
    cohort = starters[0].active_sync_groups["cohort"]
    _arrive(exp, pairs, starters)
    for participant in starters:
        pairs.receive_participant(participant)
    db_session.commit()
    assert len(cohort.active_participants) == 2

    with Session(bind=db.engine) as other:
        other.add(
            ParticipantLinkSyncGroup(
                participant_id=newcomer.id,
                sync_group_id=cohort.id,
                active=True,
                arrival_time=timenow(),
            )
        )
        other.commit()

    assert pairs.choose_who_to_release(starters) == []
    assert cohort.accepts_top_ups
