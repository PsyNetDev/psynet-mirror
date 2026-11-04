import datetime
import enum
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from dallinger import db
from dallinger.db import redis_conn
from dallinger.models import RealtimeSession, timenow
from dallinger.realtime import RealtimeGame, Reject, Sent, store
from dallinger.realtime.game import queued_effects
from dallinger.realtime.runner import Runner
from dallinger.realtime.store import RUNNING
from flask import Flask
from pydantic import BaseModel, ConfigDict, Field, field_validator
from rq import Queue, SimpleWorker

from psynet import live_session
from psynet.bot import Bot
from psynet.experiment import Experiment, get_experiment
from psynet.live_session import (
    LiveMessage,
    LiveSession,
    LiveSessionControl,
    LiveSessionInitializer,
    live_session_id,
)
from psynet.modular_page import ModularPage
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
    return _pair(db_session, [new_participant(experiment) for _ in range(2)])


@pytest.fixture
def bot_and_person(db_session, monkeypatch):
    """A pair group of a bot and a person, and the experiment's initializer."""
    # Bot() otherwise waits for a launched server and opens its first page.
    monkeypatch.setattr(
        Bot, "wait_until_experiment_launch_is_complete", lambda self: None
    )
    monkeypatch.setattr(Bot, "_advance_to_first_page", lambda self: None)
    return _pair(db_session, [Bot(), new_participant(get_experiment())])


def _pair(db_session, members):
    experiment = get_experiment()
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


def _rendered_js_vars(page, participant, monkeypatch):
    rendered = {}

    def capture(template_string, **template_args):
        rendered.update(template_args)
        return ""

    monkeypatch.setattr("psynet.timeline.render_string_with_translations", capture)
    with Flask(__name__).test_request_context("/timeline"):
        page.render(get_experiment(), participant)
    return rendered["js_vars"]


def test_a_live_session_page_gets_its_session_when_it_renders(pair, monkeypatch):
    members, initializer = pair
    page = ModularPage(
        "game", "Play.", LiveSessionControl(initializer.id), time_estimate=5
    )

    assert _rendered_js_vars(page, members[0], monkeypatch)["liveSession"] == {
        "initializerId": initializer.id,
        "sessionId": None,
        "gameChannel": None,
    }
    for member in members:
        _arrive(initializer, member)

    session_id = live_session_id(members[1], initializer.id)
    assert _rendered_js_vars(page, members[1], monkeypatch)["liveSession"] == {
        "initializerId": initializer.id,
        "sessionId": session_id,
        "gameChannel": "pick_numbers",
    }


def test_a_page_variable_can_t_share_the_control_s_name(pair, monkeypatch):
    members, initializer = pair
    page = ModularPage(
        "game",
        "Play.",
        LiveSessionControl(initializer.id),
        time_estimate=5,
        js_vars={"liveSession": "mine"},
    )

    with pytest.raises(
        ValueError,
        match="Duplicate JavaScript variable 'liveSession': contributed by "
        "the page's js_vars or a component's get_js_vars and control "
        "LiveSessionControl.",
    ):
        _rendered_js_vars(page, members[0], monkeypatch)


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


def _problems(reason):
    """A rejection's reason with its problems as a set, since Pydantic's
    versions list them in different orders."""
    head, _, problems = reason.partition(" message: ")
    return head, set(problems.removesuffix(".").split("; "))


def _pick_numbers():
    return {game.channel: game for game in get_experiment().realtime_games}[
        "pick_numbers"
    ]()


@pytest.mark.parametrize(
    "message, reason",
    [
        (
            {"type": "pick", "message": {"number": "7", "colour": "red"}},
            "Invalid 'pick' message: colour: Extra inputs are not permitted; "
            "number: Input should be a valid integer.",
        ),
        (
            {"type": "pick", "message": 7},
            "Invalid 'pick' message: Input should be an object.",
        ),
        (
            {"type": "pick"},
            "Invalid 'pick' message: number: Field required.",
        ),
        ({"type": "choose", "message": {}}, "Unknown message type 'choose'."),
        ({"type": "x" * 60}, f"Unknown message type '{'x' * 50}'."),
        (
            {"type": "pick", "message": {"number": 7}, "round": 1},
            'A message is an object with a "type" and a "message".',
        ),
        (7, 'A message is an object with a "type" and a "message".'),
        ({"type": ["pick"]}, 'A message is an object with a "type" and a "message".'),
    ],
)
def test_a_message_that_doesn_t_match_its_type_is_rejected(message, reason):
    game = _pick_numbers()
    state = game.initial_state(["1", "2"])

    with pytest.raises(Reject) as rejected:
        game.apply(state, "1", message, 0.5, Sent())

    assert _problems(rejected.value.reason) == _problems(reason)
    assert state == {"picks": {"1": None, "2": None}}


def _pair_session(pair):
    members, initializer = pair
    for member in members:
        _arrive(initializer, member)
    return live_session_id(members[0], initializer.id)


def _play_to_the_end(session_id, messages):
    """Play the session, sending each ``(player_id, number, payload)`` as a
    page would, a little apart, until it ends, and write its record."""
    runner = Runner(store.experiment_games(), name="test-runner")
    playing = threading.Thread(target=runner.run)
    playing.start()
    try:
        # Messages that arrive before the runner starts the session's clock
        # all get session time 0.
        deadline = time.monotonic() + 5
        while session_id not in runner.sessions and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session_id in runner.sessions
        for player_id, number, payload in messages:
            time.sleep(0.05)
            envelope = {"number": number, "browser_time": 1.8e9, "view_time": 0.0}
            store.add_entry(
                session_id,
                {
                    "type": "message",
                    "participant": player_id,
                    "scope": "page",
                    "data": json.dumps({"envelope": envelope, "payload": payload}),
                },
            )
        deadline = time.monotonic() + 5
        while store.running_sessions() and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        runner.stop()
        playing.join(5)
    assert not playing.is_alive()
    assert store.running_sessions() == []
    queues = [Queue(name, connection=redis_conn) for name in ("high", "default")]
    SimpleWorker(queues, connection=redis_conn).work(burst=True)


@pytest.fixture
def played(pair):
    """A pair's session, played to the end, with the pair's player ids and
    the times before and after it was played."""
    session_id = _pair_session(pair)
    first, second = (str(member.id) for member in pair[0])
    # Redis's entry IDs, which give receive times, are in whole milliseconds.
    before = timenow().replace(microsecond=0)
    _play_to_the_end(
        session_id,
        [
            (first, 1, {"type": "pick", "message": {"number": "7"}}),
            (second, 1, {"type": "guess", "message": {}}),
            (first, 2, {"type": "pick", "message": {"number": 3}}),
            (second, 2, {"type": "pick", "message": {"number": 5}}),
        ],
    )
    return session_id, first, second, before, timenow()


def test_the_game_plays_for_a_group_s_bots(bot_and_person):
    session_id = _pair_session(bot_and_person)
    bot, person = (str(member.id) for member in bot_and_person[0])

    _play_to_the_end(
        session_id, [(person, 1, {"type": "pick", "message": {"number": 5}})]
    )

    assert db.session.get(RealtimeSession, session_id).bots == [int(bot)]
    saved = live_session._live_session_types["pick_numbers"].saved_messages(session_id)
    assert [
        (message.player_id, message.status, message.message.number) for message in saved
    ] == [(bot, "accepted", int(bot)), (person, "accepted", 5)]


def test_a_played_session_s_messages_read_back_in_order_with_their_status(played):
    session_id, first, second, before, after = played

    saved = live_session._live_session_types["pick_numbers"].saved_messages(session_id)

    assert [
        (
            message.player_id,
            message.number,
            message.status,
            message.reason,
            message.message and message.message.number,
        )
        for message in saved
    ] == [
        (
            first,
            1,
            "rejected",
            "Invalid 'pick' message: number: Input should be a valid integer.",
            None,
        ),
        (second, 1, "rejected", "Unknown message type 'guess'.", None),
        (first, 2, "accepted", None, 3),
        (second, 2, "accepted", None, 5),
    ]
    assert saved[1].payload == {"type": "guess", "message": {}}
    times = [message.session_time for message in saved]
    assert times == sorted(set(times))
    assert times[-1] < (after - before).total_seconds()
    for message in saved:
        assert before <= message.receive_time <= after
        assert (message.browser_time, message.view_time) == (1.8e9, 0.0)


def test_a_message_type_reads_back_only_its_own_messages(played):
    session_id, first, second, _, _ = played
    pick = live_session._live_session_types["pick_numbers"]._message_types["pick"]
    # As when Dallinger's test fixtures run experiment.py again, so the
    # caller's class isn't the one the game lists.
    pick_again = type(
        "Pick",
        (LiveMessage,),
        {
            "__module__": pick.__module__,
            "__qualname__": pick.__qualname__,
            "__annotations__": {"number": int},
            "type": "pick",
            "apply": pick.apply,
        },
    )

    saved = pick_again.saved_messages(session_id)

    assert [(message.player_id, message.number) for message in saved] == [
        (first, 1),
        (first, 2),
        (second, 2),
    ]
    assert saved[0].message is None
    assert all(isinstance(message.message, pick_again) for message in saved[1:])


def test_a_message_its_type_can_no_longer_read_comes_back_without_it(
    played, monkeypatch, caplog
):
    session_id, first, second, _, _ = played
    game_type = live_session._live_session_types["pick_numbers"]

    class Pick(LiveMessage):
        type = "pick"
        number: int

        @field_validator("number")
        @classmethod
        def refuse(cls, number):
            raise TypeError("not any more")

        def apply(self, game, state, player_id, now):
            pass

    monkeypatch.setattr(game_type, "_message_types", {"pick": Pick})

    with caplog.at_level("WARNING", logger="psynet"):
        saved = game_type.saved_messages(session_id)

    assert [(message.number, message.status, message.message) for message in saved] == [
        (1, "rejected", None),
        (1, "rejected", None),
        (2, "accepted", None),
        (2, "accepted", None),
    ]
    assert saved[2].payload == {"type": "pick", "message": {"number": 3}}
    # The two picks that pass the field checks reach the validator. The
    # others fail a check, as a page's message can, which isn't logged.
    (record,) = caplog.records
    assert record.getMessage().startswith(
        f"2 of session {session_id}'s saved messages came back with message None"
    )
    assert "not any more" in caplog.text


def test_a_message_type_can_t_read_a_game_that_isn_t_defined(pair, monkeypatch):
    session_id = _pair_session(pair)
    pick = live_session._live_session_types["pick_numbers"]._message_types["pick"]
    monkeypatch.setattr(live_session, "_live_session_types", {})

    with pytest.raises(ValueError, match="no LiveSession with that channel"):
        pick.saved_messages(session_id)


def test_a_game_reads_back_only_its_own_sessions(pair, monkeypatch):
    session_id = _pair_session(pair)
    monkeypatch.setattr(live_session, "_live_session_types", {})

    class Elsewhere(LiveSession):
        channel = "elsewhere"

    with pytest.raises(ValueError, match="of 'pick_numbers', not 'elsewhere'"):
        Elsewhere.saved_messages(session_id)
    with pytest.raises(KeyError):
        Elsewhere.saved_messages(session_id + 1)


class OtherPick(LiveMessage):
    type = "pick"
    number: int

    def apply(self, game, state, player_id, now):
        pass


@pytest.mark.parametrize("message_type", ["OtherPick", "Move"])
def test_a_message_type_reads_back_only_sessions_of_games_that_list_it(
    pair, message_type
):
    session_id = _pair_session(pair)
    reader = globals()[message_type]

    with pytest.raises(ValueError, match=f"doesn't list {message_type} "):
        reader.saved_messages(session_id)
    with pytest.raises(KeyError):
        reader.saved_messages(session_id + 1)


class Move(LiveMessage):
    type = "move"
    to: tuple[int, int]

    def apply(self, game, state, player_id, now):
        state["held"] = type(self.to).__name__
        state["at"] = self.to


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(live_session, "_live_session_types", {})
    return live_session._live_session_types


class Point(BaseModel):
    x: int
    y: int


class Place(LiveMessage):
    type = "place"
    at: Point
    heading: float = 0

    def apply(self, game, state, player_id, now):
        state["at"] = self.at


@pytest.fixture
def walk(registry):
    class Walk(LiveSession):
        channel = "walk"
        messages = [Move, Place]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

    return Walk()


def test_a_field_holds_its_type_and_is_stored_as_json(walk):
    state = {}

    walk.apply(state, "1", {"type": "move", "message": {"to": [2, 3]}}, 0, Sent())

    assert state == {"held": "tuple", "at": [2, 3]}


def test_a_nested_model_is_stored_as_a_dict(walk):
    state = {}

    walk.apply(
        state, "1", {"type": "place", "message": {"at": {"x": 1, "y": 2}}}, 0, Sent()
    )

    assert state == {"at": {"x": 1, "y": 2}}


class Jump(LiveMessage):
    type = "jump"
    from_: int = Field(alias="from")
    to: tuple[int, int]

    def apply(self, game, state, player_id, now):
        state["jumped"] = [self.from_, self.to]


@pytest.fixture
def hop(registry):
    class Hop(LiveSession):
        channel = "hop"
        messages = [Jump]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

        def bot(self, view, player_id, now):
            return Jump(**{"from": 1, "to": (2, 3)})

    return Hop


def test_a_bot_s_message_is_sent_as_a_page_sends_it(hop):
    class FurtherHop(hop):
        channel = "further_hop"

        def bot(self, view, player_id, now):
            # Its parent's message, as a Jump.
            message = super().bot(view, player_id, now)
            return message.model_copy(update={"to": (4, 5)})

    game = FurtherHop()
    message = game.bot({}, "1", 0)

    assert message == {"type": "jump", "message": {"from": 1, "to": [4, 5]}}
    state = {}
    game.apply(state, "1", message, 0, Sent())
    assert state == {"jumped": [1, [4, 5]]}


def test_a_bot_can_return_what_a_page_sends(hop):
    sent = {"type": "jump", "message": {"from": 1, "to": [2, 3]}}

    class PlainHop(hop):
        channel = "plain_hop"

        def bot(self, view, player_id, now):
            return sent

    assert PlainHop().bot({}, "1", 0) == sent


class Aim(LiveMessage):
    type = "aim"
    x: int

    def apply(self, game, state, player_id, now):
        pass


class AimHidden(Aim):
    x: int = Field(default=0, exclude=True)


class Stray(Aim):
    type = "stray"


@pytest.mark.parametrize(
    "listed, returned, problem",
    [
        (AimHidden, AimHidden(x=7), "It reads back as AimHidden(x=0)."),
        (Aim, Stray(x=1), "Unknown message type 'stray'."),
    ],
)
def test_a_bot_message_the_game_can_t_read_as_it_is_fails_loudly(
    registry, listed, returned, problem
):
    class Archery(LiveSession):
        channel = "archery"
        messages = [listed]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

        def bot(self, view, player_id, now):
            return returned

    with pytest.raises(TypeError) as raised:
        Archery().bot({}, "1", 0)

    assert str(raised.value) == (
        f"Archery.bot returned {returned!r}, which the game can't read as it "
        f"is. {problem} A bot can also return what a page sends, as a dict."
    )


def test_a_rejection_lists_at_most_five_problems(registry):
    class Many(LiveMessage):
        type = "many"
        numbers: list[int]

        def apply(self, game, state, player_id, now):
            pass

    class Counting(LiveSession):
        messages = [Many]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

    message = {"type": "many", "message": {"numbers": ["a"] * 8}}

    with pytest.raises(Reject) as rejected:
        Counting().apply({}, "1", message, 0, Sent())

    assert rejected.value.reason == (
        "Invalid 'many' message: "
        + "; ".join(f"numbers.{i}: Input should be a valid integer" for i in range(5))
        + "; and 3 more."
    )


@pytest.mark.parametrize(
    "fields, reason",
    [
        (
            {"at": {"x": "1", "y": 2, "z": 3}},
            "Invalid 'place' message: at.z: Extra inputs are not permitted; "
            "at.x: Input should be a valid integer.",
        ),
        (
            {"at": {"x": 1, "y": 2}, "heading": float("nan")},
            "Invalid 'place' message: heading: Input should be a finite number.",
        ),
    ],
)
def test_model_fields_and_numbers_are_checked_strictly(walk, fields, reason):
    with pytest.raises(Reject) as rejected:
        walk.apply({}, "1", {"type": "place", "message": fields}, 0, Sent())

    assert _problems(rejected.value.reason) == _problems(reason)


def test_realtime_games_lists_every_live_session_and_the_listed_games(registry):
    class Listed(RealtimeGame):
        channel = "listed"

    class Played(LiveSession):
        channel = "played"

    class AlsoListed(LiveSession):
        channel = "also_listed"

    class Unplayed(LiveSession):
        """A base class for games, with no channel."""

    class Games(Experiment):
        realtime_games = [Listed, AlsoListed]
        timeline = Timeline(InfoPage("No initializer.", time_estimate=5))

    class SameGames(Games):
        pass

    assert Games.realtime_games == [Listed, AlsoListed, Played]
    assert SameGames.realtime_games == [Listed, AlsoListed, Played]


def _import_games(tmp_path, name, directory):
    games = tmp_path / directory / "games.py"
    games.parent.mkdir(exist_ok=True)
    games.write_text(
        "from psynet.live_session import LiveSession\n"
        "class Imported(LiveSession):\n"
        "    channel = 'imported'\n"
    )
    spec = importlib.util.spec_from_file_location(name, games)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[name]
    return module


def test_a_copy_imported_under_the_same_name_is_the_same_game(registry, tmp_path):
    _import_games(tmp_path, "games", "original")
    copy = _import_games(tmp_path, "games", "copy")

    assert registry == {"imported": copy.Imported}


def test_a_file_imported_under_two_names_is_refused(registry, tmp_path):
    _import_games(tmp_path, "games", "original")

    with pytest.raises(ValueError, match="one file imported under two names"):
        _import_games(tmp_path, "experiment_games", "original")


def test_a_game_defined_after_the_experiment_class_is_refused(registry):
    class Early(Experiment):
        timeline = Timeline(InfoPage("No initializer.", time_estimate=5))

    class Late(LiveSession):
        channel = "late"

    with pytest.raises(RuntimeError, match="Late must be defined or imported before"):
        Early.check_live_session_games()


def test_a_subclass_with_its_parent_s_channel_is_refused(registry):
    class Parent(LiveSession):
        channel = "shared"

    with pytest.raises(ValueError, match="Parent and Child both use the channel"):

        class Child(Parent):
            pass


class NoType(LiveMessage):
    def apply(self, game, state, player_id, now):
        pass


class NoApply(LiveMessage):
    type = "no_apply"


class AlsoMove(Move):
    pass


def test_an_annotated_type_is_refused():
    with pytest.warns(UserWarning):

        class Annotated(LiveMessage):
            type: str = "annotated"

            def apply(self, game, state, player_id, now):
                pass

    with pytest.raises(TypeError, match="Annotated.type has an annotation"):

        class Game(LiveSession):
            messages = [Annotated]


def test_an_initializer_s_game_type_must_be_a_live_session_with_a_channel(
    registry,
):
    class Plain(RealtimeGame):
        channel = "plain"

    class Unnamed(LiveSession):
        pass

    with pytest.raises(TypeError, match="game_type must be a LiveSession subclass"):
        LiveSessionInitializer(id_="plain", group_type="pair", game_type=Plain)
    with pytest.raises(TypeError, match="Unnamed has no channel"):
        LiveSessionInitializer(id_="unnamed", group_type="pair", game_type=Unnamed)


@pytest.mark.parametrize(
    "listed, error",
    [
        ([dict], "lists <class 'dict'>, which isn't a LiveMessage subclass"),
        ([NoType], "NoType.type must be a non-empty string"),
        ([NoApply], "NoApply must define apply"),
        ([Move, AlsoMove], "Move and AlsoMove both have the type 'move'"),
    ],
)
def test_a_game_s_message_types_are_checked_when_it_is_defined(registry, listed, error):
    with pytest.raises((TypeError, ValueError), match=error):

        class Game(LiveSession):
            messages = listed


class Colour(enum.Enum):
    RED = "red"


class Thing:
    pass


@pytest.mark.parametrize(
    "value, converted",
    [
        ((1, 2), [1, 2]),
        ({3}, [3]),
        (Colour.RED, "red"),
        (datetime.datetime(2026, 11, 2, 9, 30), "2026-11-02T09:30:00"),
        (datetime.timedelta(seconds=90), "PT1M30S"),
        (Point(x=1, y=2), {"x": 1, "y": 2}),
        ({1: (2, 3)}, {"1": [2, 3]}),
    ],
)
def test_the_state_is_converted_to_json_after_each_method_that_changes_it(
    registry, value, converted
):
    class Store(LiveSession):
        def initial_state(self, players):
            return {"value": value}

        def view(self, state, player_id):
            return state

        def tick(self, state, now):
            state["value"] = value

        def on_join(self, state, player_id, now):
            state["value"] = value

        def on_leave(self, state, player_id, now):
            state["value"] = value

    game = Store()
    assert game.initial_state(["1"]) == {"value": converted}
    for name, args in [("tick", (0,)), ("on_join", ("1", 0)), ("on_leave", ("1", 0))]:
        state = {}
        getattr(game, name)(state, *args)
        assert state == {"value": converted}, name


def test_the_state_s_own_keys_are_converted(registry):
    class Numbered(LiveSession):
        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

        def tick(self, state, now):
            state[1] = "a"

    state = {}

    Numbered().tick(state, 0)

    assert state == {"1": "a"}


def test_an_overridden_apply_and_a_list_state_are_converted(registry):
    class Overridden(LiveSession):
        messages = [Move]

        def initial_state(self, players):
            return []

        def view(self, state, player_id):
            return state

        def apply(self, state, player_id, message, now, sent):
            state.append(self.read_message(message).to)

    class ViaSuper(Overridden):
        def apply(self, state, player_id, message, now, sent):
            super().apply(state, player_id, message, now, sent)
            state.append(Colour.RED)

    state = []
    message = {"type": "move", "message": {"to": [2, 3]}}

    ViaSuper().apply(state, "1", message, 0, Sent())

    assert state == [[2, 3], "red"]


def test_a_method_from_a_mixin_is_converted(registry):
    class Timer:
        def tick(self, state, now):
            state["at"] = (now,)

    class Timed(Timer, LiveSession):
        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

    state = {}

    Timed().tick(state, 1)

    assert state == {"at": [1]}


def test_a_method_that_calls_another_keeps_its_references_until_it_returns(
    registry,
):
    class Nested(LiveSession):
        def initial_state(self, players):
            return {"players": {}}

        def view(self, state, player_id):
            return state

        def tick(self, state, now):
            state["ticked"] = (now,)

        def on_join(self, state, player_id, now):
            players = state["players"]
            self.tick(state, now)
            players[player_id] = (now,)

    state = {"players": {}}

    Nested().on_join(state, "1", 2)

    assert state == {"players": {"1": [2]}, "ticked": [2]}


def test_initial_state_keeps_its_references_while_it_calls_a_state_method(
    registry,
):
    class Joining(LiveSession):
        def initial_state(self, players):
            state = {"scores": {}}
            scores = state["scores"]
            for player_id in players:
                self.on_join(state, player_id, 0)
                scores[player_id] = (0,)
            return state

        def view(self, state, player_id):
            return state

        def on_join(self, state, player_id, now):
            state.setdefault("joined", []).append((player_id,))

    assert Joining().initial_state(["1", "2"]) == {
        "scores": {"1": [0], "2": [0]},
        "joined": [["1"], ["2"]],
    }


def test_a_game_that_inherits_apply_keeps_the_order_of_its_bases(registry):
    class Plain(LiveSession):
        messages = [Move]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

    class Logged(LiveSession):
        messages = [Move]

        def apply(self, state, player_id, message, now, sent):
            state["logged"] = (True,)
            super().apply(state, player_id, message, now, sent)

    class Both(Plain, Logged):
        pass

    state = {}

    Both().apply(state, "1", {"type": "move", "message": {"to": [2, 3]}}, 0, Sent())

    assert state == {"logged": [True], "held": "tuple", "at": [2, 3]}


def test_the_state_is_converted_after_a_rejected_message(registry):
    class Ticking(LiveSession):
        messages = [Move]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

        def tick(self, state, now):
            state["ticked"] = (now,)

    game = Ticking()
    state = {}
    with pytest.raises(Reject):
        game.apply(state, "1", {"type": "jump", "message": {}}, 0, Sent())

    game.tick(state, 1)

    assert state == {"ticked": [1]}


class Paint(LiveMessage):
    type = "paint"
    colour: Colour
    when: datetime.datetime

    def apply(self, game, state, player_id, now):
        game.queue_effect("painted", {"colour": self.colour, "when": self.when})


def test_an_effect_s_payload_is_converted_to_json(registry):
    class Painting(LiveSession):
        messages = [Paint]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

    message = {
        "type": "paint",
        "message": {"colour": "red", "when": "2026-11-03T09:30:00"},
    }
    effects = []
    token = queued_effects.set(effects)
    try:
        Painting().apply({}, "1", message, 0, Sent())
        with pytest.raises(ValueError, match="'kept' effect's payload holds a value"):
            Painting().queue_effect("kept", {"thing": Thing()})
    finally:
        queued_effects.reset(token)

    assert effects == [("painted", {"colour": "red", "when": "2026-11-03T09:30:00"})]


def test_a_game_can_turn_the_conversion_off(registry):
    class Converted(LiveSession):
        messages = [Move]

        def initial_state(self, players):
            return {"start": (0, 0)}

        def view(self, state, player_id):
            return state

        def tick(self, state, now):
            state["ticked"] = (1, 1)

    class Unconverted(Converted):
        convert_state_to_json = False

    game = Unconverted()
    state = game.initial_state(["1"])
    game.tick(state, 0)
    game.apply(state, "1", {"type": "move", "message": {"to": [2, 3]}}, 0, Sent())

    assert state == {"start": (0, 0), "ticked": (1, 1), "held": "tuple", "at": (2, 3)}


def test_a_state_that_can_t_be_converted_fails_loudly(registry):
    class Keep(LiveSession):
        def initial_state(self, players):
            return {"thing": Thing()}

        def view(self, state, player_id):
            return state

        def tick(self, state, now):
            state["thing"] = Thing()

        def on_join(self, state, player_id, now):
            state["loop"] = loop = []
            loop.append(loop)

        def on_leave(self, state, player_id, now):
            state["keys"] = {frozenset(): 1}

    with pytest.raises(ValueError, match="After Keep.initial_state, the state holds"):
        Keep().initial_state(["1"])
    with pytest.raises(ValueError, match="After Keep.tick, .* unknown type"):
        Keep().tick({}, 0)
    with pytest.raises(ValueError, match="After Keep.on_join, .* Circular"):
        Keep().on_join({}, "1", 0)
    with pytest.raises(ValueError, match="After Keep.on_leave, .*frozenset"):
        Keep().on_leave({}, "1", 0)


class Holds(LiveMessage):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    type = "holds"
    thing: Thing

    def apply(self, game, state, player_id, now):
        pass


def test_a_field_pydantic_can_t_read_from_json_is_refused(registry):
    with pytest.raises(TypeError, match="Holds has a field of a type Pydantic can't"):

        class Game(LiveSession):
            messages = [Holds]
