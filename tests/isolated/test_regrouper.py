import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from dallinger import db
from dallinger.models import timenow
from sqlalchemy import text
from sqlalchemy.orm import Session

from psynet import sync, timeline_hold
from psynet.bot import _backdate_arrivals, _backdate_splits, regroup_now
from psynet.db import _set_transaction_lock_timeout
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
from psynet.utils import get_psynet_root

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
    _backdate_splits(pairs, cohort[0].active_sync_groups["cohort"], 31)
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
    cohort_grouper = SimpleGrouper(
        "cohort", initial_group_size=4, quorum=2, below_quorum="fail"
    )
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
def test_every_regrouper_leaves_the_split_to_the_poller(
    in_experiment_directory, db_session
):
    """An arrival doesn't enact a due tick; the poller splits the pool instead."""
    exp = get_experiment()
    rooms = Regrouper("room", group_size=2, every=45)
    players = _working_participants(exp, 3)
    _arrive(exp, rooms, players[:2])
    _backdate_arrivals(rooms, players[:2], 60)
    _arrive(exp, rooms, players[2:])
    assert _waiting(rooms, players) == players

    sync.check_barriers()
    db_session.expire_all()
    assert _waiting(rooms, players) == players[2:]

    # Without a cohort, a player is released on arrival, as no tick is needed.
    pairs = Regrouper("pair", within="cohort", group_size=2, every=45)
    loner = _working_participants(exp, 1)
    _arrive(exp, pairs, loner)
    assert _waiting(pairs, loner) == []


class _CustomRelease(Regrouper):
    def choose_who_to_release(self, waiting_participants):
        return super().choose_who_to_release(waiting_participants)


class _CustomCheck(Regrouper):
    def check_waiting_participants(self, waiting_participants):
        return super().check_waiting_participants(waiting_participants)


@pytest.mark.parametrize("custom_rooms", [_CustomRelease, _CustomCheck])
@in_consents_experiment
def test_every_regrouper_subclass_with_custom_release_checks_on_arrival(
    in_experiment_directory, db_session, custom_rooms
):
    """A custom release rule might release on arrival, so arrivals keep the check."""
    exp = get_experiment()
    rooms = custom_rooms("custom_room", group_size=2, every=45)
    players = _working_participants(exp, 3)
    _arrive(exp, rooms, players[:2])
    _backdate_arrivals(rooms, players[:2], 60)
    _arrive(exp, rooms, players[2:])
    assert _waiting(rooms, players) == players[2:]


@in_consents_experiment
def test_waiter_timeline_get_splits_a_due_every_regrouper_pool(
    in_experiment_directory, db_session
):
    """A waiter's ``GET /timeline`` (a reload or a bot's poll) splits at a due tick."""
    exp = get_experiment()
    original = exp.timeline
    rooms = Regrouper("poll_room", group_size=2, every=45)
    exp.timeline = Timeline(rooms, ModularPage("after", "Grouped", time_estimate=1))
    try:
        players = _working_participants(exp, 2)
        for player in players:
            _json_timeline(exp, player)
        assert _waiting(rooms, players) == players
        _backdate_arrivals(rooms, players, 60)
        db_session.commit()
        _json_timeline(exp, players[0])
        db_session.expire_all()
        assert _waiting(rooms, players) == []
    finally:
        exp.timeline = original


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
        below_quorum="fail",
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
    assert (group.initial_group_size, group.quorum) == (2, 2)


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
        SimpleGrouper("lobby", initial_group_size=4, below_quorum="fail", **kwargs)


def test_simple_grouper_quorum():
    def lobby(**kwargs):
        return SimpleGrouper(
            "lobby",
            initial_group_size=4,
            max_wait_time=120,
            below_quorum="fail",
            **kwargs,
        )

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
        lobby(
            quorum=6,
            join_existing_groups=True,
            admit_newcomers="on_join",
            max_group_size=5,
        )
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
        below_quorum="fail",
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
    _backdate_splits(pairs, cohort[0].active_sync_groups["cohort"], 40)
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
    # Two were waiting at the last tick, so the poller pairs them up, not the third.
    _arrive(exp, pairs, cohort[:2])
    _backdate_arrivals(pairs, cohort[:2], 16)
    _arrive(exp, pairs, cohort[2:])
    sync.check_barriers()
    db_session.expire_all()
    assert _waiting(pairs, cohort) == cohort[2:]
    _backdate_splits(pairs, cohort[0].active_sync_groups["cohort"], 32)

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
        removed.active_sync_groups["pair"].remove_participant(
            removed, reason="removed_by_experimenter"
        )
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
    cohort_grouper = SimpleGrouper(
        "cohort", initial_group_size=n, quorum=2, below_quorum="fail"
    )
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


def _by_id(members, **_):
    return [sorted(members, key=lambda p: p.id)]


def _one_player(members, **_):
    return [members[:1]]


def _role_dict(members, barrier, **_):
    return [dict(zip(barrier.roles, members))]


def _everyone_proposes(members, **_):
    return {member: "proposer" for member in members}


def _roles_by_id(members, barrier, **_):
    return {member.id: role for member, role in zip(members, barrier.roles)}


def _demo_roles(members, barrier, **_):
    """The demo's role rule, without its rematch avoidance, which can repeat a role."""
    return _load_demo_pairing().PairingRegrouper.assign_roles(barrier, members)


def _proposers_meet_responders(members, barrier, **_):
    """Pair former proposers with former responders; those with most rounds sit out."""
    times_held = _load_demo_pairing().times_held
    ordered = sorted(
        members,
        key=lambda p: (barrier.rounds_played(p), times_held(p, "proposer"), p.id),
    )
    placed = ordered[: len(ordered) // 2 * 2]
    return [[placed[i], placed[-1 - i]] for i in range(len(placed) // 2)]


@in_consents_experiment
def test_regrouper_gives_one_member_per_role(in_experiment_directory, db_session):
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(exp, 2, form_groups=_by_id)
    _arrive(exp, pairs, cohort)
    assert sorted(_role(p) for p in cohort) == ["proposer", "responder"]

    cohort, pairs = _cohort_and_pairs(exp, 2, form_groups=_one_player)
    with pytest.raises(ValueError, match="one member per role"):
        _arrive(exp, pairs, cohort)
    cohort, pairs = _cohort_and_pairs(exp, 2, form_groups=_role_dict)
    with pytest.raises(TypeError, match="lists of participants"):
        _arrive(exp, pairs, cohort)
    cohort, pairs = _cohort_and_pairs(exp, 2, assign_roles=_everyone_proposes)
    with pytest.raises(ValueError, match="each role to one member"):
        _arrive(exp, pairs, cohort)
    cohort, pairs = _cohort_and_pairs(exp, 2, assign_roles=_roles_by_id)
    with pytest.raises(TypeError, match="keyed by participants"):
        _arrive(exp, pairs, cohort)


def _role(participant):
    """Return the participant's role in their current pair, or ``None``."""
    group = participant.active_sync_groups.get("pair")
    if group is None:
        return None
    (link,) = [
        link
        for link in group.participant_links
        if link.participant_id == participant.id and link.active
    ]
    return link.role


def _partner(participant):
    (partner,) = [
        p
        for p in participant.active_sync_groups["pair"].participants
        if p is not participant
    ]
    return partner


@in_consents_experiment
def test_regrouper_alternates_roles_and_counts_rounds(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(
        exp, 4, form_groups=_proposers_meet_responders, assign_roles=_demo_roles
    )

    _arrive(exp, pairs, cohort)
    first = {p.id: _role(p) for p in cohort}
    assert sorted(first.values()) == ["proposer"] * 2 + ["responder"] * 2
    assert all(_role(_partner(p)) != _role(p) for p in cohort)

    _arrive(exp, pairs, cohort)
    for p in cohort:
        assert _role(p) != first[p.id]
        assert pairs.rounds_played(p) == 2
        assert p.sync_group_removal_reason("pair") is None
    cohort[0].active_sync_groups["pair"].remove_participant(
        cohort[0], reason="removed_by_experimenter"
    )

    # Three players left: one sits out, and plays first next round.
    cohort[0].active_sync_groups["cohort"].remove_participant(
        cohort[3], reason="removed_by_experimenter"
    )
    _arrive(exp, pairs, cohort[:3])
    (sitter,) = [p for p in cohort[:3] if "pair" not in p.active_sync_groups]
    assert _role(sitter) is None
    assert (pairs.rounds_sat_out(sitter), pairs.sat_out(sitter)) == (1, True)
    # cohort[0] was removed from their pair above, so the regrouper didn't move them on.
    expected_reason = "removed_by_experimenter" if sitter is cohort[0] else "moved_on"
    assert sitter.sync_group_removal_reason("pair") == expected_reason
    _arrive(exp, pairs, cohort[:3])
    assert "pair" in sitter.active_sync_groups
    assert not pairs.sat_out(sitter)


def _scripted_pair(members, **_):
    first, second = _scripted_pair.script.pop(0)
    ordered = sorted(members, key=lambda p: p.id)
    return [[ordered[first], ordered[second]]]


def _load_demo_pairing():
    path = get_psynet_root() / "demos/experiments/ultimatum_pairing/pairing.py"
    spec = importlib.util.spec_from_file_location("ultimatum_pairing_pairing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@in_consents_experiment
def test_demo_pairing_spots_a_rematch_after_a_sit_out(
    in_experiment_directory, db_session
):
    """A played B, then sat out while B played C: A and B are still last partners."""
    pairing = _load_demo_pairing()
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(exp, 3, form_groups=_scripted_pair)
    a, b, c = sorted(cohort, key=lambda p: p.id)
    _scripted_pair.script = [(0, 1), (1, 2)]
    _arrive(exp, pairs, cohort)
    _arrive(exp, pairs, cohort)
    assert pairing.is_rematch(a, b) and pairing.is_rematch(b, a)
    assert not pairing.is_rematch(a, c)


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


def _open_cohorts(
    stop_top_ups_after_rounds, initial_group_size=2, below_quorum="fail", **kwargs
):
    cohort_grouper = SimpleGrouper(
        "cohort",
        initial_group_size=initial_group_size,
        quorum=initial_group_size,
        max_group_size=6,
        join_existing_groups=True,
        admit_newcomers="on_join",
        below_quorum=below_quorum,
    )
    pairs = Regrouper(
        "pair",
        within="cohort",
        group_size=2,
        stop_top_ups_after_rounds=stop_top_ups_after_rounds,
        **kwargs,
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
def test_a_split_into_several_groups_counts_as_one_round(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(2, initial_group_size=4)
    players = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, players)
    cohort = players[0].active_sync_groups["cohort"]
    for _ in range(2):
        _arrive(exp, pairs, players)
        assert cohort.accepts_top_ups
    _arrive(exp, pairs, players)
    assert not cohort.accepts_top_ups


@in_consents_experiment
def test_a_closing_split_of_sit_outs_alone_stops_top_ups(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(
        1, initial_group_size=3, deadline=15, left_over="sit_out"
    )
    players = _working_participants(exp, 3)
    _arrive(exp, cohort_grouper, players)
    cohort = players[0].active_sync_groups["cohort"]
    _arrive(exp, pairs, players)
    (sitter,) = [p for p in players if "pair" not in p.active_sync_groups]
    assert cohort.accepts_top_ups

    # The pair is still playing, so the sitter sits out again an extra deadline later.
    _backdate_splits(pairs, cohort, 40)
    _arrive(exp, pairs, [sitter])
    _backdate_arrivals(pairs, [sitter], 31)
    assert pairs.choose_who_to_release([sitter]) == [sitter]
    assert not cohort.accepts_top_ups


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
                admitted_at=timenow(),
            )
        )
        other.commit()

    assert pairs.choose_who_to_release(starters) == []
    assert cohort.accepts_top_ups


@in_consents_experiment
def test_a_round_of_latecomers_alone_counts_towards_closing_the_cohort(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(1, deadline=30)
    *starters, c, d, too_late = _working_participants(exp, 5)
    _arrive(exp, cohort_grouper, starters)
    cohort = starters[0].active_sync_groups["cohort"]
    _arrive(exp, pairs, starters)
    _arrive(exp, cohort_grouper, [c, d])
    # The starters are still playing, so the latecomers pair at the deadline.
    _arrive(exp, pairs, [c, d])
    _backdate_splits(pairs, cohort, 31)
    _backdate_arrivals(pairs, [c, d], 31)
    assert set(pairs.choose_who_to_release([c, d])) == {c, d}
    db_session.commit()

    assert not cohort.accepts_top_ups
    _arrive(exp, cohort_grouper, [too_late])
    assert not too_late.in_sync_group("cohort")


@pytest.mark.parametrize("below_quorum", ["fail", "continue_without_group"])
@in_consents_experiment
def test_closing_a_cohort_below_quorum_dissolves_it_without_a_split(
    in_experiment_directory, db_session, below_quorum
):
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(
        0,
        initial_group_size=3,
        below_quorum=below_quorum,
        on_release=_count_releases,
        roles=["proposer", "responder"],
    )
    *present, gone = _working_participants(exp, 3)
    _arrive(exp, cohort_grouper, [*present, gone])
    cohort = gone.active_sync_groups["cohort"]
    gone.status = "returned"
    for participant in present:
        pairs.receive_participant(participant)
    db_session.commit()
    _count_releases.calls = 0

    assert set(pairs.choose_who_to_release(present)) == set(present)
    assert not cohort.active and _count_releases.calls == 0
    assert all(pairs.rounds_played(p) == 0 and _role(p) is None for p in present)
    expected_tags = ["sync group below quorum"] if below_quorum == "fail" else []
    assert all(p.failure_tags == expected_tags for p in present)


@in_consents_experiment
def test_a_closing_split_skips_a_cohort_another_request_holds(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(0)
    starters = _working_participants(exp, 2)
    _arrive(exp, cohort_grouper, starters)
    cohort = starters[0].active_sync_groups["cohort"]
    for participant in starters:
        pairs.receive_participant(participant)
    db_session.commit()

    with Session(bind=db.engine) as busy_request:
        busy_request.execute(
            text("SELECT id FROM sync_group WHERE id = :id FOR UPDATE"),
            {"id": cohort.id},
        )
        assert pairs.choose_who_to_release(starters) == []
    assert cohort.accepts_top_ups


@in_consents_experiment
def test_a_cohort_waiting_to_dissolve_is_not_split(in_experiment_directory, db_session):
    """Closing a cohort below quorum while a member is busy pairs nobody meanwhile."""
    exp = get_experiment()
    cohort_grouper, pairs = _open_cohorts(0, initial_group_size=4, deadline=30)
    *present, busy, gone = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, [*present, busy, gone])
    cohort = gone.active_sync_groups["cohort"]
    gone.status = "returned"
    for participant in present:
        pairs.receive_participant(participant)
    _backdate_arrivals(pairs, present, 31)
    db_session.commit()

    with Session(bind=db.engine) as busy_request:
        busy_request.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": busy.id},
        )
        for _ in range(2):
            # Fails rather than hangs if marking the cohort waits for a lock.
            _set_transaction_lock_timeout(1)
            assert pairs.choose_who_to_release(present) == []
            db_session.commit()
        assert cohort.dissolving and not pairs.would_release(present)
    assert all(pairs.rounds_played(p) == 0 for p in present)


@in_consents_experiment
def test_backdating_reaches_the_deadline_after_quick_splits(
    in_experiment_directory, db_session
):
    """``regroup_now``'s backdating starts a round after two quick earlier ones.

    A player still in last round's pair keeps their role meanwhile.
    """
    exp = get_experiment()
    cohort_grouper = SimpleGrouper(
        "cohort", initial_group_size=4, quorum=2, below_quorum="fail"
    )
    pairs = Regrouper(
        "pair",
        within="cohort",
        roles=["proposer", "responder"],
        deadline=30,
        left_over="sit_out",
    )
    players = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, players)
    cohort = players[0].active_sync_groups["cohort"]
    for _ in range(2):
        _arrive(exp, pairs, players)
    present, lingering = players[:3], players[3]
    lingering_role = _role(lingering)
    assert lingering_role in ("proposer", "responder")
    _arrive(exp, pairs, present)
    assert all(_role(p) is None for p in present)  # Waiting for the split.

    _backdate_splits(pairs, cohort, 30)
    _backdate_arrivals(pairs, present, 30)
    assert _role(lingering) == lingering_role
    assert len(pairs.choose_who_to_release(present)) == 3
    db_session.commit()
    (sitter,) = [p for p in present if "pair" not in p.active_sync_groups]
    assert _role(sitter) is None
    assert _role(lingering) == lingering_role


@in_consents_experiment
def test_backdating_reaches_the_every_tick(in_experiment_directory, db_session):
    """``regroup_now``'s backdating reaches the next ``every`` tick."""
    exp = get_experiment()
    cohort_grouper = SimpleGrouper(
        "cohort", initial_group_size=4, quorum=2, below_quorum="fail"
    )
    pairs = Regrouper("pair", within="cohort", group_size=2, every=600)
    players = _working_participants(exp, 4)
    _arrive(exp, cohort_grouper, players)
    cohort = players[0].active_sync_groups["cohort"]
    _arrive(exp, pairs, players)
    assert pairs.choose_who_to_release(players) == []

    _backdate_splits(pairs, cohort, 600)
    _backdate_arrivals(pairs, players, 600)
    assert len(pairs.choose_who_to_release(players)) == 4


@in_consents_experiment
def test_regroup_now_needs_a_timed_regrouper_and_a_waiting_bot(
    in_experiment_directory, db_session
):
    bot = SimpleNamespace(id=_working_participants(get_experiment(), 1)[0].id)
    with pytest.raises(ValueError, match="no deadline or every"):
        regroup_now([bot], Regrouper("pair", within="cohort", group_size=2))
    with pytest.raises(ValueError, match="None of the bots"):
        regroup_now(
            [bot], Regrouper("pair", within="cohort", group_size=2, deadline=30)
        )


@in_consents_experiment
def test_case_an_odd_player_out_sits_out_then_plays_the_next_round(
    in_experiment_directory, db_session
):
    """Checks a case of docs/code/multiplayer/late_slow_and_leaving_players.rst."""
    exp = get_experiment()
    cohort, pairs = _cohort_and_pairs(exp, 3)
    _arrive(exp, pairs, cohort)
    (sitter,) = [p for p in cohort if "pair" not in p.active_sync_groups]
    players = [p for p in cohort if p is not sitter]
    assert _waiting(pairs, cohort) == []
    assert (pairs.sat_out(sitter), _role(sitter)) == (True, None)
    assert sorted(_role(p) for p in players) == ["proposer", "responder"]

    # Back first, the sitter waits for the pair, then plays the next round.
    _arrive(exp, pairs, [sitter])
    assert _waiting(pairs, [sitter]) == [sitter]
    _arrive(exp, pairs, players)
    assert _waiting(pairs, cohort) == []
    assert "pair" in sitter.active_sync_groups
    assert [pairs.sat_out(p) for p in players].count(True) == 1


@in_consents_experiment
def test_a_regrouper_split_admits_pending_members_of_its_within_group(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    cohort_grouper = SimpleGrouper(
        "cohort",
        initial_group_size=2,
        max_group_size=3,
        target_group_size=2,
        join_existing_groups=True,
        admit_newcomers="at_admission_point",
        below_quorum="continue_without_group",
    )
    trios = Regrouper("trio", within="cohort", group_size=3, deadline=30)
    founders = _working_participants(exp, 2)
    _arrive(exp, cohort_grouper, founders)
    (newcomer,) = _working_participants(exp, 1)
    _arrive(exp, cohort_grouper, [newcomer])
    cohort = founders[0].active_sync_groups["cohort"]
    assert cohort.pending_participants == [newcomer]

    _arrive(exp, trios, [*founders, newcomer])

    assert cohort.pending_participants == []
    assert set(cohort.active_participants) == {*founders, newcomer}
    assert set(newcomer.active_sync_groups["trio"].participants) == {
        *founders,
        newcomer,
    }
    links = [p.sync_group_link("cohort") for p in (*founders, newcomer)]
    assert [link.admission_points_passed for link in links] == [1, 1, 1]
