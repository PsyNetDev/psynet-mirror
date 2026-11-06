import datetime
import enum
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import numpy
import pytest
from dallinger import db
from dallinger.db import redis_conn
from dallinger.models import RealtimeSession, timenow
from dallinger.realtime import RealtimeGame, Reject, Sent, store
from dallinger.realtime.core import new_session, run_pass
from dallinger.realtime.game import queued_effects
from dallinger.realtime.runner import Runner
from dallinger.realtime.store import RUNNING
from flask import Flask
from pydantic import BaseModel, ConfigDict, Field, field_validator
from rq import Queue, SimpleWorker

from psynet.bot import Bot
from psynet.experiment import Experiment, get_experiment
from psynet.live_session import (
    NOT_STARTED,
    LiveMessage,
    LiveSession,
    LiveSessionControl,
    LiveSessionInitializer,
    LiveSessionResult,
    Ready,
    live_session_id,
    live_session_result,
)
from psynet.live_session import registry as game_registry
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    SimpleSyncGroup,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
)
from psynet.timeline import Response, Timeline

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


def test_a_live_session_control_takes_any_control_parameter():
    control = LiveSessionControl("game", show_next_button=False, bot_response=3)

    assert control.show_next_button is False
    assert control._bot_response == 3


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


def _started(**state):
    """A state, or a view, of a session player "1" plays, which has started."""
    return {
        **state,
        "live_session": {"players": ["1"], "ready": ["1"], "started_at": 0},
    }


def _game_part(state):
    """The state without PsyNet's entry for the ready step."""
    return {key: value for key, value in state.items() if key != "live_session"}


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
    game.start_session(state, 0)

    with pytest.raises(Reject) as rejected:
        game.apply(state, "1", message, 0.5, Sent())

    assert _problems(rejected.value.reason) == _problems(reason)
    assert _game_part(state) == {"picks": {"1": None, "2": None}}


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
            (first, 1, READY),
            (first, 2, {"type": "pick", "message": {"number": 7}}),
            (second, 1, READY),
            (first, 3, {"type": "pick", "message": {"number": "7"}}),
            (second, 2, {"type": "guess", "message": {}}),
            (first, 4, {"type": "pick", "message": {"number": 3}}),
            (second, 3, {"type": "pick", "message": {"number": 5}}),
        ],
    )
    return session_id, first, second, before, timenow()


READY = {"type": "psynet_ready", "message": {}}


def _pick(number):
    return game_registry._live_session_types["pick_numbers"]._message_types["pick"](
        number=number
    )


def test_the_game_plays_for_a_group_s_bots_once_they_are_ready(bot_and_person):
    session_id = _pair_session(bot_and_person)
    bot, person = (str(member.id) for member in bot_and_person[0])

    _play_to_the_end(
        session_id,
        [(person, 1, READY), (person, 2, {"type": "pick", "message": {"number": 5}})],
    )

    assert db.session.get(RealtimeSession, session_id).bots == [int(bot)]
    saved = game_registry._live_session_types["pick_numbers"].saved_messages(session_id)
    assert [
        (message.player_id, message.status, message.message) for message in saved
    ] == [
        (bot, "accepted", Ready()),
        (person, "accepted", Ready()),
        (bot, "accepted", _pick(int(bot))),
        (person, "accepted", _pick(5)),
    ]


def test_a_played_session_s_messages_read_back_in_order_with_their_status(played):
    session_id, first, second, before, after = played

    saved = game_registry._live_session_types["pick_numbers"].saved_messages(session_id)

    assert [
        (
            message.player_id,
            message.number,
            message.status,
            message.reason,
            message.message,
        )
        for message in saved
    ] == [
        (first, 1, "accepted", None, Ready()),
        (first, 2, "rejected", NOT_STARTED, _pick(7)),
        (second, 1, "accepted", None, Ready()),
        (
            first,
            3,
            "rejected",
            "Invalid 'pick' message: number: Input should be a valid integer.",
            None,
        ),
        (second, 2, "rejected", "Unknown message type 'guess'.", None),
        (first, 4, "accepted", None, _pick(3)),
        (second, 3, "accepted", None, _pick(5)),
    ]
    assert saved[4].payload == {"type": "guess", "message": {}}
    times = [message.session_time for message in saved]
    assert times == sorted(set(times))
    assert times[-1] < (after - before).total_seconds()
    for message in saved:
        assert before <= message.receive_time <= after
        assert (message.browser_time, message.view_time) == (1.8e9, 0.0)


def test_a_message_type_reads_back_only_its_own_messages(played):
    session_id, first, second, _, _ = played
    pick = game_registry._live_session_types["pick_numbers"]._message_types["pick"]
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
        (first, 2),
        (first, 3),
        (first, 4),
        (second, 3),
    ]
    assert saved[1].message is None
    assert all(
        isinstance(message.message, pick_again)
        for i, message in enumerate(saved)
        if i != 1
    )


def test_a_message_its_type_can_no_longer_read_comes_back_without_it(
    played, monkeypatch, caplog
):
    session_id, first, second, _, _ = played
    game_type = game_registry._live_session_types["pick_numbers"]

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
        (1, "accepted", None),
        (2, "rejected", None),
        (1, "accepted", None),
        (3, "rejected", None),
        (2, "rejected", None),
        (4, "accepted", None),
        (3, "accepted", None),
    ]
    assert saved[5].payload == {"type": "pick", "message": {"number": 3}}
    # The three picks that pass the field checks reach the validator. The
    # others fail a check, as a page's message can, which isn't logged.
    (record,) = caplog.records
    assert record.getMessage().startswith(
        f"3 of session {session_id}'s saved messages came back with message None"
    )
    assert "not any more" in caplog.text


def test_a_message_type_can_t_read_a_game_that_isn_t_defined(pair, monkeypatch):
    session_id = _pair_session(pair)
    pick = game_registry._live_session_types["pick_numbers"]._message_types["pick"]
    monkeypatch.setattr(game_registry, "_live_session_types", {})

    with pytest.raises(ValueError, match="no LiveSession with that channel"):
        pick.saved_messages(session_id)


def test_a_game_reads_back_only_its_own_sessions(pair, monkeypatch):
    session_id = _pair_session(pair)
    monkeypatch.setattr(game_registry, "_live_session_types", {})

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
    monkeypatch.setattr(game_registry, "_live_session_types", {})
    return game_registry._live_session_types


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
    state = _started()

    walk.apply(state, "1", {"type": "move", "message": {"to": [2, 3]}}, 0, Sent())

    assert _game_part(state) == {"held": "tuple", "at": [2, 3]}


def test_a_nested_model_is_stored_as_a_dict(walk):
    state = _started()

    walk.apply(
        state, "1", {"type": "place", "message": {"at": {"x": 1, "y": 2}}}, 0, Sent()
    )

    assert _game_part(state) == {"at": {"x": 1, "y": 2}}


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
    message = game.bot(_started(), "1", 0)

    assert message == {"type": "jump", "message": {"from": 1, "to": [4, 5]}}
    state = _started()
    game.apply(state, "1", message, 0, Sent())
    assert _game_part(state) == {"jumped": [1, [4, 5]]}


def test_a_bot_can_return_what_a_page_sends(hop):
    sent = {"type": "jump", "message": {"from": 1, "to": [2, 3]}}

    class PlainHop(hop):
        channel = "plain_hop"

        def bot(self, view, player_id, now):
            return sent

    assert PlainHop().bot(_started(), "1", 0) == sent


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
        Archery().bot(_started(), "1", 0)

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
        Counting().apply(_started(), "1", message, 0, Sent())

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
        walk.apply(_started(), "1", {"type": "place", "message": fields}, 0, Sent())

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


def test_an_initializer_s_game_type_must_be_a_live_session_with_a_channel_and_a_bot(
    registry,
):
    class Plain(RealtimeGame):
        channel = "plain"

    class Unnamed(LiveSession):
        def bot(self, view, player_id, now):
            return None

    class Botless(LiveSession):
        channel = "botless"

    with pytest.raises(TypeError, match="game_type must be a LiveSession subclass"):
        LiveSessionInitializer(id_="plain", group_type="pair", game_type=Plain)
    with pytest.raises(TypeError, match="Unnamed has no channel"):
        LiveSessionInitializer(id_="unnamed", group_type="pair", game_type=Unnamed)
    with pytest.raises(TypeError, match="Botless has no bot method"):
        LiveSessionInitializer(id_="botless", group_type="pair", game_type=Botless)


@pytest.mark.parametrize(
    "listed, error",
    [
        ([dict], "lists <class 'dict'>, which isn't a LiveMessage subclass"),
        ([NoType], "NoType.type must be a non-empty string"),
        ([NoApply], "NoApply must define apply"),
        ([Move, AlsoMove], "Move and AlsoMove both have the type 'move'"),
        ([Ready], "lists Ready, with the type 'psynet_ready', which is PsyNet's"),
        ([Ready, Move], "lists Ready, with the type 'psynet_ready', which is PsyNet's"),
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

        def on_start(self, state, now):
            state["value"] = value

    game = Store()
    assert _game_part(game.initial_state(["1"])) == {"value": converted}
    for name, args in [
        ("tick", (0,)),
        ("on_join", ("1", 0)),
        ("on_leave", ("1", 0)),
        ("on_start", (0,)),
    ]:
        state = _started()
        getattr(game, name)(state, *args)
        assert _game_part(state) == {"value": converted}, name


def test_the_state_s_own_keys_are_converted(registry):
    class Numbered(LiveSession):
        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

        def tick(self, state, now):
            state[1] = "a"

    state = _started()

    Numbered().tick(state, 0)

    assert _game_part(state) == {"1": "a"}


def test_an_overridden_apply_is_converted(registry):
    class Overridden(LiveSession):
        messages = [Move]

        def initial_state(self, players):
            return {"moves": []}

        def view(self, state, player_id):
            return state

        def apply(self, state, player_id, message, now, sent):
            state["moves"].append(self.read_message(message).to)

    class ViaSuper(Overridden):
        def apply(self, state, player_id, message, now, sent):
            super().apply(state, player_id, message, now, sent)
            state["moves"].append(Colour.RED)

    state = _started(moves=[])
    message = {"type": "move", "message": {"to": [2, 3]}}

    ViaSuper().apply(state, "1", message, 0, Sent())

    assert _game_part(state) == {"moves": [[2, 3], "red"]}


def test_a_method_from_a_mixin_is_converted(registry):
    class Timer:
        def tick(self, state, now):
            state["at"] = (now,)

    class Timed(Timer, LiveSession):
        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

    state = _started()

    Timed().tick(state, 1)

    assert _game_part(state) == {"at": [1]}


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

    state = _started(players={})

    Nested().on_join(state, "1", 2)

    assert _game_part(state) == {"players": {"1": [2]}, "ticked": [2]}


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

    assert _game_part(Joining().initial_state(["1", "2"])) == {
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

    state = _started()

    Both().apply(state, "1", {"type": "move", "message": {"to": [2, 3]}}, 0, Sent())

    assert _game_part(state) == {"logged": [True], "held": "tuple", "at": [2, 3]}


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
    state = _started()
    with pytest.raises(Reject):
        game.apply(state, "1", {"type": "jump", "message": {}}, 0, Sent())

    game.tick(state, 1)

    assert _game_part(state) == {"ticked": [1]}


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
        Painting().apply(_started(), "1", message, 0, Sent())
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
    game.start_session(state, 0)
    game.tick(state, 0)
    game.apply(state, "1", {"type": "move", "message": {"to": [2, 3]}}, 0, Sent())

    assert _game_part(state) == {
        "start": (0, 0),
        "ticked": (1, 1),
        "held": "tuple",
        "at": (2, 3),
    }


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
        Keep().tick(_started(), 0)
    with pytest.raises(ValueError, match="After Keep.on_join, .* Circular"):
        Keep().on_join({}, "1", 0)
    with pytest.raises(ValueError, match="After Keep.on_leave, .*frozenset"):
        Keep().on_leave(_started(), "1", 0)


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


class Tap(LiveMessage):
    type = "tap"

    def apply(self, game, state, player_id, now):
        state["taps"].append(player_id)


TAP = {"type": "tap", "message": {}}


@pytest.fixture
def relay(registry):
    class Relay(LiveSession):
        channel = "relay"
        messages = [Tap]
        ready_timeout = 10

        def initial_state(self, players):
            return {"taps": [], "ticks": []}

        def view(self, state, player_id):
            return {"taps": len(state["taps"])}

        def tick(self, state, now):
            state["ticks"].append(now)

        def next_deadline(self, state):
            return 99

        def on_start(self, state, now):
            state["deadline"] = now + 5

        def bot(self, view, player_id, now):
            return None if view["taps"] else Tap()

    return Relay()


def test_messages_are_rejected_until_every_player_is_ready(relay):
    state = relay.initial_state(["1", "2"])

    with pytest.raises(Reject) as rejected:
        relay.apply(state, "1", TAP, 1, Sent())
    for player_id, now in [("1", 2), ("1", 3), ("2", 4)]:
        relay.apply(state, player_id, READY, now, Sent())
    relay.apply(state, "1", TAP, 5, Sent())

    assert rejected.value.reason == NOT_STARTED
    assert state == {
        "taps": ["1"],
        "ticks": [],
        "deadline": 9,
        "live_session": {"players": ["1", "2"], "ready": ["1", "2"], "started_at": 4},
    }


def test_an_overridden_apply_gets_only_the_game_s_messages_after_the_start(relay):
    class Counted(type(relay)):
        channel = "counted"

        def apply(self, state, player_id, message, now, sent):
            state["applied"] = state.get("applied", 0) + 1
            super().apply(state, player_id, message, now, sent)

    game = Counted()
    state = game.initial_state(["1"])

    with pytest.raises(Reject, match=NOT_STARTED):
        game.apply(state, "1", TAP, 1, Sent())
    game.apply(state, "1", READY, 2, Sent())
    game.apply(state, "1", TAP, 3, Sent())

    assert (state["applied"], state["taps"]) == (1, ["1"])


def test_the_session_starts_at_the_ready_timeout_without_everyone(relay):
    state = relay.initial_state(["1", "2"])
    relay.apply(state, "1", READY, 1, Sent())

    assert relay.next_deadline(state) == 10
    relay.tick(state, 9.9)
    assert (state["live_session"]["started_at"], state["ticks"]) == (None, [])

    relay.tick(state, 10)
    assert state["live_session"] == {
        "players": ["1", "2"],
        "ready": ["1"],
        "started_at": 10,
    }
    assert (state["ticks"], state["deadline"]) == ([10], 15)
    assert relay.next_deadline(state) == 99
    relay.apply(state, "2", READY, 11, Sent())
    relay.apply(state, "2", TAP, 12, Sent())
    assert state["live_session"]["started_at"] == 10
    assert (state["taps"], state["deadline"]) == (["2"], 15)


def test_without_a_ready_timeout_the_session_waits_for_everyone(relay):
    class Patient(type(relay)):
        channel = "patient"
        ready_timeout = None

    game = Patient()
    state = game.initial_state(["1"])

    assert game.next_deadline(state) is None
    game.tick(state, 1000)

    assert state["live_session"]["started_at"] is None


def advance(self, state, now):
    state["ticks"].append(now)


class Clock(RealtimeGame):
    def tick(self, state, now):
        state["ticks"].append(now)

    def next_deadline(self, state):
        return 99

    def on_leave(self, state, player_id, now):
        state["left"] = player_id


def test_the_ready_step_covers_renamed_methods_and_later_bases(relay):
    class Renamed(type(relay)):
        channel = "renamed"
        tick = advance

    class Later(LiveSession, Clock):
        channel = "later"

        def initial_state(self, players):
            return {"ticks": []}

        def view(self, state, player_id):
            return {}

    for game in [Renamed(), Later()]:
        state = game.initial_state(["1"])
        game.tick(state, 1)
        game.apply(state, "1", READY, 2, Sent())
        game.tick(state, 3)

        assert state["ticks"] == [3], type(game).__name__
        assert game.next_deadline(state) == 99
    game.on_leave(state, "1", 4)
    assert state["left"] == "1"


def test_a_game_can_build_on_another_game_s_state(relay):
    class Extended(type(relay)):
        channel = "extended"

        def initial_state(self, players):
            return {**super().initial_state(players), "deadline": None}

    state = Extended().initial_state(["1"])

    assert state == {
        "taps": [],
        "ticks": [],
        "deadline": None,
        "live_session": {"players": ["1"], "ready": [], "started_at": None},
    }


def test_each_view_shows_who_is_ready_and_when_the_session_started(relay):
    state = relay.initial_state(["1", "2"])
    relay.apply(state, "2", READY, 1, Sent())

    assert relay.view(state, "1") == {
        "taps": 0,
        "live_session": {"players": ["1", "2"], "ready": ["2"], "started_at": None},
    }


def test_a_player_who_leaves_before_the_start_is_not_ready(relay):
    state = relay.initial_state(["1", "2"])

    relay.apply(state, "1", READY, 1, Sent())
    relay.on_leave(state, "1", 2)
    relay.apply(state, "2", READY, 3, Sent())
    assert state["live_session"]["started_at"] is None
    relay.apply(state, "1", READY, 4, Sent())
    relay.on_leave(state, "1", 5)

    assert state["live_session"] == {
        "players": ["1", "2"],
        "ready": ["2", "1"],
        "started_at": 4,
    }


def test_a_game_method_that_calls_another_gets_the_ready_step(relay):
    class Eager(type(relay)):
        channel = "eager"

        def on_join(self, state, player_id, now):
            self.tick(state, now)

    game = Eager()
    state = game.initial_state(["1"])

    game.on_join(state, "1", 1)

    assert state["ticks"] == []


CLOCK = 1.8e9


def _entry(kind, time, player_id, payload=None):
    """A session entry, as the web process adds it, for run_pass."""
    entry = {"type": kind, "time": time, "participant": player_id, "scope": "page"}
    if kind == "message":
        entry.update(data=json.dumps(payload), received=CLOCK + time)
    else:
        entry["socket"] = f"{player_id}/page"
    return entry


def test_a_deadline_due_by_the_ready_timeout_runs_when_the_session_starts(relay):
    class Overdue(type(relay)):
        channel = "overdue"

        def next_deadline(self, state):
            return 5

        def is_over(self, state):
            return bool(state["ticks"])

    game = Overdue()
    entries = [_entry("join", 0, "1"), _entry("message", 1, "1", READY)]

    waiting = run_pass(game, new_session(game, ["1", "2"]), entries, 2, CLOCK)
    ended = run_pass(game, waiting.saved, [], 10, CLOCK)

    assert waiting.next_due == 10
    assert ended.ended["reason"] == "finished"
    assert json.loads(ended.saved)["state"]["ticks"] == [10]


def test_an_on_start_that_ends_the_game_skips_its_tick(relay):
    class Everyone(type(relay)):
        channel = "everyone"

        def on_start(self, state, now):
            ready_step = state["live_session"]
            state["everyone"] = ready_step["ready"] == ready_step["players"]

        def is_over(self, state):
            return state.get("everyone") is False

    game = Everyone()
    entries = [_entry("join", 0, "1"), _entry("message", 1, "1", READY)]

    waiting = run_pass(game, new_session(game, ["1", "2"]), entries, 2, CLOCK)
    ended = run_pass(game, waiting.saved, [], 10, CLOCK)

    assert ended.ended["reason"] == "finished"
    assert json.loads(ended.saved)["state"]["ticks"] == []


def test_a_bot_is_ready_at_once_and_plays_once_the_session_starts(relay):
    state = relay.initial_state(["1", "2"])

    def bot_message(now):
        return relay.bot(relay.view(state, "1"), "1", now)

    assert bot_message(0) == READY
    with pytest.raises(ValueError, match="The view has no 'live_session' entry"):
        relay.bot({"taps": 0}, "1", 0)
    relay.apply(state, "1", READY, 0, Sent())
    assert bot_message(0) is None
    relay.apply(state, "2", READY, 1, Sent())
    assert bot_message(1) == TAP


@pytest.mark.parametrize(
    "state, view, error",
    [
        ([], {}, "Game.initial_state must return a dict, not list"),
        ({"live_session": 1}, {}, "a 'live_session' entry, which is PsyNet's"),
        ({}, [], "Game.view must return a dict, not list"),
        ({}, {"live_session": 1}, "Game.view returned a 'live_session' entry"),
    ],
)
def test_the_state_and_views_are_dicts_without_psynet_s_entry(
    registry, state, view, error
):
    class Game(LiveSession):
        def initial_state(self, players):
            return state

        def view(self, state, player_id):
            return view

    with pytest.raises((TypeError, ValueError), match=error):
        game = Game()
        game.view(game.initial_state(["1"]), "1")


@pytest.mark.parametrize("ready_timeout", [0, -1, "30", float("inf")])
def test_a_ready_timeout_is_none_or_a_positive_number(registry, ready_timeout):
    with pytest.raises(ValueError, match="Game's ready_timeout must be None"):
        type("Game", (LiveSession,), {"ready_timeout": ready_timeout})


def _game_page():
    (page,) = [
        elt
        for elt in get_experiment().timeline.all_elts
        if isinstance(elt, ModularPage) and elt.label == "pick_numbers"
    ]
    return page


def _submit_on_the_game_page(member):
    """Send the game page's response through the response route, with an
    answer of the page's own, and return the route's payload."""
    experiment = get_experiment()
    member.elt_id = _game_page().id
    db.session.commit()
    result = experiment.process_response(
        participant_id=member.id,
        raw_answer="sent by the page",
        blobs={},
        metadata={"time_taken": 1},
        page_uuid=member.page_uuid,
        client_ip_address="127.0.0.1",
    )
    db.session.commit()
    return result.payload


def _accepted_answers(member):
    return [
        answer
        for (answer,) in db.session.query(Response.answer).filter_by(
            participant_id=member.id,
            question="pick_numbers",
            successful_validation=True,
        )
    ]


def _reward(member):
    return (
        db.session.query(Participant.performance_reward)
        .filter_by(id=member.id)
        .scalar()
    )


def test_the_game_page_answers_with_the_outcome_once_the_result_is_saved(pair):
    members, _ = pair
    session_id = _pair_session(pair)
    first, second = (str(member.id) for member in members)

    payload = _submit_on_the_game_page(members[0])

    assert payload == {
        "submission": "rejected",
        "message": "Please wait while the game finishes...",
        "retry_after": 1,
    }
    # A response the page sends again leaves nothing behind.
    assert (
        db.session.query(Response).filter_by(participant_id=members[0].id).count() == 0
    )
    assert live_session_result(session_id) is None

    _play_to_the_end(
        session_id,
        [
            (first, 1, READY),
            (second, 1, READY),
            (first, 2, {"type": "pick", "message": {"number": 3}}),
            (second, 2, {"type": "pick", "message": {"number": 5}}),
        ],
    )
    # The worker that wrote the record closed the database session.
    members = [db.session.get(Participant, int(member)) for member in (first, second)]
    # Each Pick's bonus effect is handled as the record is written.
    assert _reward(members[0]) == pytest.approx(0.5)

    assert _submit_on_the_game_page(members[0])["submission"] == "approved"

    outcome = {first: 3, second: 5}
    assert live_session_result(session_id) == LiveSessionResult(
        "ended", "finished", outcome
    )
    assert _accepted_answers(members[0]) == [outcome]
    # The game's bonus is the player's pick, in hundredths.
    assert _reward(members[0]) == pytest.approx(0.53)
    assert _reward(members[1]) == pytest.approx(0.5)

    # Another visit to the page answers again, without paying the bonus again.
    assert _submit_on_the_game_page(members[0])["submission"] == "approved"
    assert _accepted_answers(members[0]) == [outcome, outcome]
    assert _reward(members[0]) == pytest.approx(0.53)


@pytest.mark.parametrize(
    "end_reason, outcome, record_complete",
    [("failed", {"1": None}, True), (None, None, False)],
)
def test_a_failed_session_s_page_moves_on_with_what_was_saved(
    pair, monkeypatch, end_reason, outcome, record_complete
):
    members, _ = pair
    session_id = _pair_session(pair)
    # How Dallinger saves a session that failed in the game's code, or one
    # whose record couldn't be written.
    db.session.query(RealtimeSession).filter_by(id=session_id).update(
        {"status": "failed", "end_reason": end_reason, "outcome": outcome}
    )
    bonuses = []
    game_type = game_registry._live_session_types["pick_numbers"]
    # A game that computes bonuses with NumPy returns a NumPy number.
    monkeypatch.setattr(
        game_type,
        "bonus",
        lambda self, *args: bonuses.append(args) or numpy.float64(0.25),
    )

    assert _submit_on_the_game_page(members[0])["submission"] == "approved"

    result = live_session_result(session_id)
    assert result.record_complete is record_complete
    assert _accepted_answers(members[0]) == [outcome]
    if record_complete:
        assert bonuses == [(outcome, "failed", str(members[0].id))]
        assert _reward(members[0]) == pytest.approx(0.25)
    else:
        assert bonuses == []
        assert _reward(members[0]) == 0


def test_a_game_page_without_a_session_moves_on_with_no_answer(pair):
    members, _ = pair

    assert _submit_on_the_game_page(members[0])["submission"] == "approved"
    assert _accepted_answers(members[0]) == [None]


def test_live_session_result_needs_a_session(db_session):
    with pytest.raises(KeyError):
        live_session_result(12345)


@pytest.mark.parametrize("amount", [-1, "1"])
def test_a_bonus_is_a_number_0_or_more(pair, monkeypatch, amount):
    members, _ = pair
    session_id = _pair_session(pair)
    db.session.query(RealtimeSession).filter_by(id=session_id).update(
        {"status": "ended", "end_reason": "finished", "outcome": {}}
    )
    game_type = game_registry._live_session_types["pick_numbers"]
    monkeypatch.setattr(game_type, "bonus", lambda self, *args: amount)
    # So the response route raises the error rather than showing an error page.
    monkeypatch.setenv("PASSTHROUGH_ERRORS", "1")

    with pytest.raises(
        ValueError, match=f"PickNumbers.bonus gave the bonus {amount!r}"
    ):
        _submit_on_the_game_page(members[0])
    with pytest.raises(ValueError, match="PickNumbers.queue_bonus gave the bonus"):
        game_type().queue_bonus("1", amount)


def test_a_game_s_own_handle_effect_gets_its_effects_but_not_its_bonuses(
    pair, registry
):
    members, _ = pair
    session_id = _pair_session(pair)
    handled = []

    class Scored(LiveSession):
        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return {}

        def handle_effect(self, name, payload, session_row):
            handled.append(name)

    effects = []
    token = queued_effects.set(effects)
    try:
        # The player id as a string, as the game receives it, or as the
        # participant's integer id.
        Scored().queue_bonus(str(members[0].id), 0.5)
        Scored().queue_bonus(members[0].id, numpy.int64(1))
        Scored().queue_bonus(members[0].id, 0)
        Scored().queue_effect("scored", {})
    finally:
        queued_effects.reset(token)
    assert [name for name, _ in effects] == ["psynet_bonus", "psynet_bonus", "scored"]
    row = db.session.get(RealtimeSession, session_id)
    for name, payload in effects:
        Scored().handle_effect(name, payload, row)

    assert handled == ["scored"]
    assert _reward(members[0]) == pytest.approx(1.5)
    with pytest.raises(ValueError, match="'99', who isn't a player in session"):
        Scored().handle_effect("psynet_bonus", {"player_id": "99", "amount": 1}, row)
    with pytest.raises(ValueError, match="'psynet_bonus' is reserved for PsyNet's"):
        Scored().queue_effect("psynet_bonus", {})


class ValidatingPage(ModularPage):
    def validate(self, response, **kwargs):
        return None


@pytest.mark.parametrize(
    "page_type, kwargs",
    [(ModularPage, {"validate": lambda response: None}), (ValidatingPage, {})],
)
def test_a_live_session_page_can_t_have_a_validate_of_its_own(page_type, kwargs):
    with pytest.raises(TypeError, match="LiveSessionControl and a validate function"):
        page_type("game", "Play", LiveSessionControl("pick_numbers"), **kwargs)
