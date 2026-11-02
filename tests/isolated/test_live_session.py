import sys
from pathlib import Path

import pytest
from dallinger import db
from dallinger.db import redis_conn
from dallinger.models import RealtimeSession
from dallinger.realtime import RealtimeGame
from dallinger.realtime.store import RUNNING

from psynet.experiment import Experiment, get_experiment
from psynet.live_session import LiveSessionInitializer, live_session_id
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    SimpleSyncGroup,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
)
from psynet.timeline import Timeline

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from timeline_hold_helpers import new_participant  # noqa: E402

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("live_session")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


@pytest.fixture
def pair(db_session):
    """A pair group, its leader first, and the experiment's initializer."""
    experiment = get_experiment()
    members = [new_participant(experiment) for _ in range(2)]
    group = SimpleSyncGroup(
        group_type="pair",
        initial_group_size=2,
        max_group_size=2,
        min_group_size=2,
        n_active_participants=2,
        accepts_top_ups=False,
    )
    db_session.add(group)
    for member in members:
        member.status = "working"
        group.add_participant(member)
    group.leader = members[0]
    db_session.commit()
    (initializer,) = {
        elt.links["barrier"]
        for elt in experiment.timeline.all_elts
        if isinstance(elt.links.get("barrier"), LiveSessionInitializer)
    }
    return members, initializer


def _arrive(initializer, member):
    """Arrive as the response route does: commit, then check the barrier."""
    initializer.receive_participant(member)
    initializer.waiting_logic.consume(get_experiment(), member)
    db.session.commit()
    _run_pending_barrier_checks(_take_pending_barrier_checks())
    db.session.commit()


def test_each_pass_through_the_initializer_starts_a_new_session(pair):
    members, initializer = pair
    members[0].live_sessions = {"earlier": 7}
    session_ids = []
    for _ in range(2):
        _arrive(initializer, members[0])
        assert live_session_id(members[0], initializer.id) is None
        _arrive(initializer, members[1])
        session_ids.append(live_session_id(members[0], initializer.id))

    assert None not in session_ids
    assert session_ids[0] != session_ids[1]
    assert live_session_id(members[0], "earlier") == 7


def test_a_follower_who_reloads_finds_the_group_s_session(pair):
    members, initializer = pair
    for member in members:
        _arrive(initializer, member)
    leader_session = live_session_id(members[0], initializer.id)
    follower_id = members[1].id
    member_ids = sorted(member.id for member in members)
    db.session.expunge_all()

    follower = Participant.query.get(follower_id)

    session_id = live_session_id(follower, initializer.id)
    assert session_id == leader_session
    row = db.session.get(RealtimeSession, session_id)
    assert row.game_type == "pick_numbers"
    assert sorted(row.members) == member_ids
    assert redis_conn.sismember(RUNNING, session_id)


class Listed(RealtimeGame):
    channel = "listed"


class Played(RealtimeGame):
    channel = "played"


def test_realtime_games_adds_the_timeline_s_game_types_to_the_listed_ones():
    class TwoGames(Experiment):
        realtime_games = [Listed]
        timeline = Timeline(
            LiveSessionInitializer(id_="first", group_type="pair", game_type=Played),
            LiveSessionInitializer(id_="second", group_type="pair", game_type=Played),
        )

    class SameTimeline(TwoGames):
        pass

    class NewTimeline(TwoGames):
        timeline = Timeline(InfoPage("No games.", time_estimate=5))

    assert TwoGames.realtime_games == [Listed, Played]
    assert SameTimeline.realtime_games == [Listed, Played]
    assert NewTimeline.realtime_games == [Listed]
