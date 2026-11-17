import datetime
import enum
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

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

import psynet
from psynet.bot import Bot
from psynet.experiment import Experiment, get_experiment
from psynet.live_game import (
    NOT_STARTED,
    PLAYERS_LEFT,
    TIMEOUT,
    LiveGame,
    LiveGameControl,
    LiveGameRecord,
    LiveMessage,
    PlayerReady,
    PlayLiveGame,
)
from psynet.live_game import registry as game_registry
from psynet.live_game.messages import _session_participant_ids
from psynet.live_game.testing import LocalGame, start_game
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    SimpleSyncGroup,
    SyncGroupRound,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
)
from psynet.timeline import Response, Timeline
from psynet.trial.main import Trial

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from timeline_hold_helpers import new_participant  # noqa: E402

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("live_game")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


@pytest.fixture
def pair(db_session):
    """A pair group, its leader first, and the experiment's game barrier."""
    experiment = get_experiment()
    return _pair(db_session, [new_participant(experiment) for _ in range(2)])


@pytest.fixture
def bot_and_person(db_session, monkeypatch):
    """A pair group of a bot and a person, and the experiment's game barrier."""
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
        quorum=2,
        n_active_participants=2,
        accepts_top_ups=False,
        below_quorum="continue_without_group",
    )
    db_session.add(group)
    for member in members:
        member.status = "working"
        group.add_participant(member)
    group.leader = members[0]
    db_session.commit()
    (game_barrier,) = {
        elt.links["barrier"]
        for elt in experiment.timeline.all_elts
        if getattr(elt.links.get("barrier"), "id", None) == "pick_numbers"
    }
    return members, game_barrier


def _play(id_="trial_game", page=None, **kwargs):
    """A PlayLiveGame of the pick-numbers game, as a trial's show_trial
    builds one for each participant."""
    if page is None:
        page = ModularPage(id_, "Play.", LiveGameControl(), time_estimate=5)
    kwargs.setdefault("game_class", type(_pick_numbers()))
    if "late_after" not in kwargs:
        kwargs.setdefault("max_wait_time", 60)
    return PlayLiveGame(id_=id_, group_type="pair", page=page, **kwargs)


def _page_of(game_barrier, page_kwargs=None, **control_kwargs):
    """A game page that plays the session ``game_barrier`` starts."""
    page = ModularPage(
        "game",
        "Play.",
        LiveGameControl(**control_kwargs),
        time_estimate=5,
        **(page_kwargs or {}),
    )
    _play(game_barrier.id, page)
    return page


def _reach(game_barrier, member):
    """Run the game barrier's first step, which every participant who reaches
    it takes, one who has left the group included."""
    first, *barrier = game_barrier.resolve()
    assert barrier
    first.consume(get_experiment(), member)


def _arrive(game_barrier, member):
    """Arrive as the response route does: commit, then check the barrier."""
    _reach(game_barrier, member)
    game_barrier.receive_participant(member)
    game_barrier.waiting_logic.consume(get_experiment(), member)
    db.session.commit()
    _run_pending_barrier_checks(_take_pending_barrier_checks())
    db.session.commit()


def _game_id(participant, play_id):
    game = participant.live_games.get(play_id)
    return None if game is None else game.id


def test_each_pass_through_the_game_barrier_starts_a_new_game(pair):
    members, game_barrier = pair
    members[0].live_game_data = {
        "earlier": {
            "id": 7,
            "history": [{"id": 6, "answer": "lost"}, {"id": 7, "answer": "won"}],
        }
    }
    session_ids = []
    for _ in range(2):
        _arrive(game_barrier, members[0])
        assert members[0].live_games[game_barrier.id].status == "not_started"
        _arrive(game_barrier, members[1])
        session_ids.append(members[0].live_games[game_barrier.id].id)

    assert None not in session_ids
    assert session_ids[0] != session_ids[1]
    games = members[0].live_games
    assert (games["earlier"].id, games["earlier"].answer) == (7, "won")
    assert games[game_barrier.id].answer is None
    # Every game the participant played at each step, oldest first, with
    # their answer in each.
    history = members[0].live_game_history
    assert [(game.id, game.answer) for game in history["earlier"]] == [
        (6, "lost"),
        (7, "won"),
    ]
    assert [game.id for game in history[game_barrier.id]] == session_ids
    assert "never_reached" not in games


def test_a_participant_who_reaches_the_game_barrier_again_has_no_game_yet(pair):
    members, game_barrier = pair
    session_id = _pair_session(pair)
    assert _game_id(members[1], game_barrier.id) == session_id

    # A participant who has left the group passes the barrier without
    # arriving at it.
    _reach(game_barrier, members[1])

    assert _game_id(members[1], game_barrier.id) is None
    assert _game_id(members[0], game_barrier.id) == session_id


def test_the_page_script_sends_the_ready_message_s_type():
    script = Path(psynet.__file__).parent / "resources/scripts/live-game.js"

    assert f'const READY = "{PlayerReady.type}";' in script.read_text()


def test_a_game_starts_from_its_game_barrier_s_settings(pair):
    session_id = _pair_session(pair)

    assert store.realtime_state(session_id)["pick_reward"] == 0.5
    # Only a session the game barrier starts gets them.
    assert _pick_numbers().initial_state(["1"])["pick_reward"] == 0


def test_an_game_barrier_s_settings_must_be_json_the_game_takes(registry, monkeypatch):
    class Fixed(LiveGame):
        name = "fixed"

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return {}

        def bot(self, view, player_id, now):
            return None

    class Varied(Fixed):
        name = "varied"

        def initial_state(self, players, settings):
            return {"settings": settings}

    def game_barrier(game_class, settings):
        return _play("game", game_class=game_class, settings=settings).barrier

    # A group's release rebuilds the game barrier, so it has to find the game.
    with pytest.raises(TypeError, match="'game' can't be saved: .* is a local class"):
        game_barrier(Fixed, None)
    for game_class in (Fixed, Varied):
        game_class.__qualname__ = game_class.__name__
        monkeypatch.setitem(globals(), game_class.__name__, game_class)

    with pytest.raises(TypeError, match="Fixed.initial_state takes no settings"):
        game_barrier(Fixed, {"rounds": 3})
    with pytest.raises(TypeError, match="settings for Varied can't be saved as JSON"):
        game_barrier(Varied, {"rounds": {3}})
    with pytest.raises(TypeError, match="Varied.initial_state needs settings"):
        game_barrier(Varied, None)
    assert game_barrier(Fixed, None).settings is None
    given = {"rounds": (3, 5)}
    assert game_barrier(Varied, given).settings == {"rounds": [3, 5]}
    # A test calls the game with settings directly.
    assert _game_part(Varied().initial_state(["1"], {"rounds": 3})) == {
        "settings": {"rounds": 3}
    }


def _trial_game_barrier(settings):
    """The barrier of a PlayLiveGame with settings from a trial's definition."""
    return _play(settings=settings).barrier


def test_each_round_s_game_barriers_start_a_game_with_that_round_s_settings(pair):
    members, _ = pair
    rewards = []
    for pick_reward in (0.1, 0.2):
        for member in members:
            _arrive(_trial_game_barrier({"pick_reward": pick_reward}), member)
        session_id = _game_id(members[0], "trial_game")
        assert _game_id(members[1], "trial_game") == session_id
        rewards.append(store.realtime_state(session_id)["pick_reward"])

    assert rewards == [0.1, 0.2]


def test_a_group_with_fewer_than_min_players_starts_no_game(pair, monkeypatch):
    members, game_barrier = pair
    monkeypatch.setattr(type(_pick_numbers()), "min_players", 3)

    for member in members:
        _arrive(game_barrier, member)

    assert _game_id(members[0], game_barrier.id) is None


_releases = []


def _note_release(participants, live_game):
    _releases.append((sorted(p.id for p in participants), live_game.id))


@pytest.mark.parametrize("min_players, starts", [(2, True), (3, False)])
def test_on_release_runs_when_the_group_s_game_is_created(
    pair, monkeypatch, min_players, starts
):
    members, _ = pair
    monkeypatch.setattr(type(_pick_numbers()), "min_players", min_players)
    game_barrier = _play(on_release=_note_release).barrier
    _releases.clear()

    for member in members:
        _arrive(game_barrier, member)

    game_id = _game_id(members[0], "trial_game")
    assert (game_id is not None) is starts
    # With no game, because the group is too small, the record's id is None.
    assert _releases == [(sorted(m.id for m in members), game_id)]


class UnpaidGame(LiveGame):
    """A game that pays nothing itself, for a trial that pays."""

    name = "unpaid_game"

    def initial_state(self, players):
        return {}

    def view(self, state, player):
        return {}

    def bot(self, view, player, now):
        return None


def test_a_game_and_the_trial_it_s_played_in_can_t_both_pay():
    from psynet.trial.main import Trial

    class PaysPerWin:
        def compute_performance_reward(self, score):
            return score * 0.1

    class PaysNothing:
        compute_performance_reward = Trial.compute_performance_reward

    # The pick-numbers game pays through its performance_reward.
    barrier = _play().barrier
    barrier._check_trial(PaysNothing())
    with pytest.raises(TypeError, match="PaysPerWin pays through compute_performance"):
        barrier._check_trial(PaysPerWin())

    # A game that leaves the paying to its trial, whose inherited
    # performance_reward PsyNet still wraps.
    assert UnpaidGame.performance_reward is not LiveGame.performance_reward
    _play("unpaid_game", game_class=UnpaidGame).barrier._check_trial(PaysPerWin())


def test_the_members_of_a_group_must_arrive_with_the_same_settings(pair):
    members, _ = pair
    _arrive(_trial_game_barrier({"pick_reward": 0.1}), members[0])

    with pytest.raises(
        ValueError,
        match=f"Participant {members[1].id} arrived at the PlayLiveGame "
        "'trial_game' with settings that differ from those of the members of "
        "their group who are waiting there.",
    ):
        _arrive(_trial_game_barrier({"pick_reward": 0.2}), members[1])


def test_an_game_barrier_s_settings_can_t_use_a_key_its_saved_form_reserves():
    with pytest.raises(
        TypeError,
        match="PlayLiveGame 'trial_game' can't be saved: .*'__type__'",
    ):
        _trial_game_barrier({"__type__": "fast"})


def _rendered_js_vars(page, participant, monkeypatch):
    rendered = {}

    def capture(template_string, **template_args):
        rendered.update(template_args)
        return ""

    monkeypatch.setattr("psynet.timeline.render_string_with_translations", capture)
    with Flask(__name__).test_request_context("/timeline"):
        page.render(get_experiment(), participant)
    return rendered["js_vars"]


def test_a_live_game_page_gets_its_game_when_it_renders(pair, monkeypatch):
    members, game_barrier = pair
    page = _page_of(game_barrier)

    with pytest.raises(
        ValueError,
        match=f"Participant {members[0].id} hasn't reached the PlayLiveGame "
        f"'{game_barrier.id}', whose game page",
    ):
        _rendered_js_vars(page, members[0], monkeypatch)
    _reach(game_barrier, members[0])
    assert _rendered_js_vars(page, members[0], monkeypatch)["liveGame"] == {
        "playId": game_barrier.id,
        "liveGameId": None,
        "gameChannel": None,
        "autoAdvance": True,
        "showResultFor": 0,
        "playerLeftMessage": "Another player has left the game.",
        "noGameMessage": "Your group couldn't start the game.",
        "waitingStatus": "Waiting for the other players to open the game",
        "endedStatus": "The game is over.",
        "players": [],
    }
    for member in members:
        _arrive(game_barrier, member)

    session_id = _game_id(members[1], game_barrier.id)
    js_vars = _rendered_js_vars(page, members[1], monkeypatch)["liveGame"]
    assert [player["you"] for player in js_vars.pop("players")] == [
        member.id == members[1].id for member in sorted(members, key=lambda m: m.id)
    ]
    assert js_vars == {
        "playId": game_barrier.id,
        "liveGameId": session_id,
        "gameChannel": "pick_numbers",
        "autoAdvance": True,
        "showResultFor": 0,
        "playerLeftMessage": "Another player has left the game.",
        "noGameMessage": "Your group couldn't start the game.",
        "waitingStatus": "Waiting for the other players to open the game",
        "endedStatus": "The game is over.",
    }


def test_a_live_game_page_can_leave_moving_on_to_its_javascript(pair, monkeypatch):
    members, game_barrier = pair
    page = _page_of(game_barrier, auto_advance=False)

    _reach(game_barrier, members[0])
    js_vars = _rendered_js_vars(page, members[0], monkeypatch)

    assert js_vars["liveGame"]["autoAdvance"] is False


@pytest.mark.parametrize(
    "kwargs", [{"show_result_for": -1}, {"show_result_for": 5, "auto_advance": False}]
)
def test_a_live_game_page_refuses_a_show_result_for_it_can_t_honour(kwargs):
    with pytest.raises(ValueError, match="show_result_for"):
        LiveGameControl(**kwargs)


@pytest.mark.parametrize("message", ["Your partner has left.", None])
def test_a_live_game_page_can_change_or_hide_its_player_left_notice(
    pair, monkeypatch, message
):
    members, game_barrier = pair
    page = _page_of(game_barrier, player_left_message=message)

    _reach(game_barrier, members[0])
    js_vars = _rendered_js_vars(page, members[0], monkeypatch)

    assert js_vars["liveGame"]["playerLeftMessage"] == message


@pytest.mark.parametrize("message", ["Your partner didn't arrive.", None])
def test_a_live_game_page_can_change_or_hide_its_no_game_notice(
    pair, monkeypatch, message
):
    members, game_barrier = pair
    page = _page_of(game_barrier, no_game_message=message)

    _reach(game_barrier, members[0])
    js_vars = _rendered_js_vars(page, members[0], monkeypatch)

    assert js_vars["liveGame"]["noGameMessage"] == message


def test_a_play_live_game_needs_a_game_page_of_its_own(pair):
    unnamed = PlayLiveGame(
        group_type="pair",
        game_class=type(_pick_numbers()),
        page=ModularPage("game", "Play.", LiveGameControl(), time_estimate=5),
        max_wait_time=60,
    )
    assert unnamed.barrier.id == "pick_numbers"
    with pytest.raises(TypeError, match="needs a limit on its wait"):
        PlayLiveGame(
            group_type="pair",
            game_class=type(_pick_numbers()),
            page=ModularPage("game", "Play.", LiveGameControl(), time_estimate=5),
        )

    page = ModularPage("game", "Play.", LiveGameControl(), time_estimate=5)
    # The page follows the barrier.
    assert _play("first", page).resolve()[-1] is page
    with pytest.raises(
        ValueError, match="already the page of the PlayLiveGame 'first'"
    ):
        _play("second", page)
    with pytest.raises(TypeError, match="must be a ModularPage with a LiveGameControl"):
        _play("third", InfoPage("Play.", time_estimate=5))


def test_a_live_game_page_has_to_belong_to_a_play_live_game(pair, monkeypatch):
    members, _ = pair
    page = ModularPage("game", "Play.", LiveGameControl(), time_estimate=5)

    with pytest.raises(TypeError, match="has to be the page of a PlayLiveGame"):
        _rendered_js_vars(page, members[0], monkeypatch)


def test_a_live_game_control_takes_any_control_parameter():
    control = LiveGameControl(show_next_button=False, bot_response=3)

    assert control.show_next_button is False
    assert control._bot_response == 3


def test_a_page_variable_can_t_share_the_control_s_name(pair, monkeypatch):
    members, game_barrier = pair
    page = _page_of(game_barrier, page_kwargs=dict(js_vars={"liveGame": "mine"}))
    _reach(game_barrier, members[0])

    with pytest.raises(
        ValueError,
        match="Duplicate JavaScript variable 'liveGame': contributed by "
        "the page's js_vars or a component's get_js_vars and control "
        "LiveGameControl.",
    ):
        _rendered_js_vars(page, members[0], monkeypatch)


def test_a_follower_who_reloads_finds_the_group_s_game(pair):
    members, game_barrier = pair
    for member in members:
        _arrive(game_barrier, member)
    leader_session = _game_id(members[0], game_barrier.id)
    follower_id = members[1].id
    member_ids = sorted(member.id for member in members)
    db.session.expunge_all()

    follower = Participant.query.get(follower_id)

    session_id = _game_id(follower, game_barrier.id)
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
    # From the experiment's module, since the registry fixture empties the
    # registry that realtime_games reads.
    return sys.modules[type(get_experiment()).__module__].PickNumbers()


def _psynet(**fields):
    """PsyNet's entry in a state, for a game played by participant 1 alone,
    with ``fields`` changed."""
    entry = {
        "participant_ids": [1],
        "ready": [],
        "away": [],
        "players_left": False,
        "duration": None,
        "started_at": None,
        "ends_at": None,
        "time_up": False,
        **fields,
    }
    entry.setdefault("away_since", [None] * len(entry["participant_ids"]))
    return entry


def _started(**state):
    """A state, or a view, of a game participant 1 plays alone, as player
    0, which has started."""
    return {**state, "psynet": _psynet(ready=[0], started_at=0)}


def _started_view(**view):
    """The view of player 0, participant 1, in a game they play alone, which
    has started, as Dallinger gives it to a bot."""
    entry = _psynet(ready=[0], started_at=0)
    del entry["participant_ids"]
    return {**view, "psynet": {**entry, "you": 0}}


def _game_part(state):
    """The state without PsyNet's entry for the ready step."""
    return {key: value for key, value in state.items() if key != "psynet"}


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
    start_game(game, state)

    with pytest.raises(Reject) as rejected:
        game.apply(state, "1", message, 0.5, Sent())

    assert _problems(rejected.value.reason) == _problems(reason)
    assert state["picks"] == [None, None]


def _pair_session(pair):
    members, game_barrier = pair
    for member in members:
        _arrive(game_barrier, member)
    return _game_id(members[0], game_barrier.id)


def test_a_game_page_shows_its_players_by_pseudonym(pair):
    from psynet.live_game.control import _players, _players_payload

    members, game_barrier = pair
    session_id = _pair_session(pair)
    order = _session_participant_ids(session_id)
    first = next(m for m in members if m.id == order[0])
    other = next(m for m in members if m.id == order[1])

    players = _players(first, game_barrier.id)
    assert [p["you"] for p in players] == [True, False]
    assert players[0]["label"] == "You"
    assert players[1]["label"] == players[1]["name"] == other.pseudonym.name
    assert players[1]["css_color"] == other.pseudonym.css_color
    # The page's variables carry them, and the route gives the same.
    control = _game_page().control
    assert control.play_id == game_barrier.id
    js_vars = control.get_participant_js_vars(None, first)
    assert js_vars["liveGame"]["players"] == players
    assert _players_payload(first.unique_id, game_barrier.id) == {"players": players}
    assert _players_payload("nobody", game_barrier.id) == {"players": []}
    assert _players(first, "never_reached") == []


def test_an_anonymous_game_page_never_gets_the_players_pseudonyms(db_session):
    from psynet.live_game.control import _players

    experiment = get_experiment()
    members, _ = _pair(db_session, [new_participant(experiment) for _ in range(2)])
    page = ModularPage(
        "anonymous", "Play.", LiveGameControl(names="anonymous"), time_estimate=5
    )
    barrier = _play("anonymous", page=page).barrier
    assert barrier.names == "anonymous"
    for member in members:
        _arrive(barrier, member)

    players = _players(members[0], "anonymous")
    assert [p["label"] for p in players if not p["you"]] == ["Your partner"]
    for player in players:
        assert (player["name"], player["css_color"], player["emoji"]) == (None,) * 3
        assert members[1].pseudonym.name not in str(player)
    with pytest.raises(ValueError, match="names must be one of"):
        LiveGameControl(names="hidden")


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
    return game_registry._live_game_classes["pick_numbers"]._message_types["pick"](
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
    saved = LiveGameRecord(session_id).messages
    # Players are numbered in participant id order.
    bot_player = sorted([int(bot), int(person)]).index(int(bot))
    assert [
        (message.participant_id, message.player, message.status, message.message)
        for message in saved
    ] == [
        (int(bot), bot_player, "accepted", PlayerReady()),
        (int(person), 1 - bot_player, "accepted", PlayerReady()),
        (int(bot), bot_player, "accepted", _pick(10 + bot_player)),
        (int(person), 1 - bot_player, "accepted", _pick(5)),
    ]


def test_a_played_game_s_messages_read_back_in_order_with_their_status(played):
    session_id, first, second, before, after = played

    saved = LiveGameRecord(session_id).messages

    assert [
        (
            message.player,
            message.number,
            message.status,
            message.reason,
            message.message,
        )
        for message in saved
    ] == [
        (0, 1, "accepted", None, PlayerReady()),
        (0, 2, "rejected", NOT_STARTED, _pick(7)),
        (1, 1, "accepted", None, PlayerReady()),
        (
            0,
            3,
            "rejected",
            "Invalid 'pick' message: number: Input should be a valid integer.",
            None,
        ),
        (1, 2, "rejected", "Unknown message type 'guess'.", None),
        (0, 4, "accepted", None, _pick(3)),
        (1, 3, "accepted", None, _pick(5)),
    ]
    assert [message.participant_id for message in saved[:3]] == [
        int(first),
        int(first),
        int(second),
    ]
    assert saved[4].payload == {"type": "guess", "message": {}}
    # On the game's clock, which starts with the second player's ready
    # message, so the messages before it have negative times.
    times = [message.time for message in saved]
    assert times == sorted(set(times))
    assert times[0] < times[1] < times[2] == 0
    assert times[-1] < (after - before).total_seconds()
    for message in saved:
        assert before <= message.receive_time <= after
        assert message.browser_time == 1.8e9
    # Each page's view was from session time 0, before the game started.
    view_times = {message.view_time for message in saved}
    assert len(view_times) == 1
    assert view_times.pop() <= times[0] < 0


def test_a_game_s_messages_of_one_type_are_picked_out_by_their_type(
    played, monkeypatch
):
    session_id, first, second, _, _ = played
    pick = game_registry._live_game_classes["pick_numbers"]._message_types["pick"]
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

    monkeypatch.setitem(
        game_registry._live_game_classes["pick_numbers"]._message_types,
        "pick",
        pick_again,
    )
    saved = [m for m in LiveGameRecord(session_id).messages if m.type == "pick"]

    assert [(message.player, message.number) for message in saved] == [
        (0, 2),
        (0, 3),
        (0, 4),
        (1, 3),
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
    game_class = game_registry._live_game_classes["pick_numbers"]

    class Pick(LiveMessage):
        type = "pick"
        number: int

        @field_validator("number")
        @classmethod
        def refuse(cls, number):
            raise TypeError("not any more")

        def apply(self, game, state, player, now):
            pass

    monkeypatch.setattr(game_class, "_message_types", {"pick": Pick})

    with caplog.at_level("WARNING", logger="psynet"):
        saved = LiveGameRecord(session_id).messages

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
        f"3 of game {session_id}'s saved messages came back with message None"
    )
    assert "not any more" in caplog.text


def test_a_record_can_t_read_the_messages_of_a_game_that_isn_t_defined(
    pair, monkeypatch
):
    session_id = _pair_session(pair)
    monkeypatch.setattr(game_registry, "_live_game_classes", {})

    with pytest.raises(ValueError, match="no LiveGame with that name"):
        LiveGameRecord(session_id).messages


class Move(LiveMessage):
    type = "move"
    to: tuple[int, int]

    def apply(self, game, state, player_id, now):
        state["held"] = type(self.to).__name__
        state["at"] = self.to


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(game_registry, "_live_game_classes", {})
    return game_registry._live_game_classes


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
    class Walk(LiveGame):
        name = "walk"
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
    class Hop(LiveGame):
        name = "hop"
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
        name = "further_hop"

        def bot(self, view, player_id, now):
            # Its parent's message, as a Jump.
            message = super().bot(view, player_id, now)
            return message.model_copy(update={"to": (4, 5)})

    game = FurtherHop()
    message = game.bot(_started_view(), "1", 0)

    assert message == {"type": "jump", "message": {"from": 1, "to": [4, 5]}}
    state = _started()
    game.apply(state, "1", message, 0, Sent())
    assert _game_part(state) == {"jumped": [1, [4, 5]]}


def test_a_bot_can_return_what_a_page_sends(hop):
    sent = {"type": "jump", "message": {"from": 1, "to": [2, 3]}}

    class PlainHop(hop):
        name = "plain_hop"

        def bot(self, view, player_id, now):
            return sent

    assert PlainHop().bot(_started_view(), "1", 0) == sent


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
    class Archery(LiveGame):
        name = "archery"
        messages = [listed]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

        def bot(self, view, player_id, now):
            return returned

    with pytest.raises(TypeError) as raised:
        Archery().bot(_started_view(), "1", 0)

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

    class Counting(LiveGame):
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


def test_realtime_games_lists_every_live_game_and_the_listed_games(registry):
    class Listed(RealtimeGame):
        name = "listed"

    class Played(LiveGame):
        name = "played"

    class AlsoListed(LiveGame):
        name = "also_listed"

    class Unplayed(LiveGame):
        """A base class for games, with no name."""

    class Games(Experiment):
        realtime_games = [Listed, AlsoListed]
        timeline = Timeline(InfoPage("No game barrier.", time_estimate=5))

    class SameGames(Games):
        pass

    assert Games.realtime_games == [Listed, AlsoListed, Played]
    assert SameGames.realtime_games == [Listed, AlsoListed, Played]


def _import_games(tmp_path, name, directory):
    games = tmp_path / directory / "games.py"
    games.parent.mkdir(exist_ok=True)
    games.write_text(
        "from psynet.live_game import LiveGame\n"
        "class Imported(LiveGame):\n"
        "    name = 'imported'\n"
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


def test_a_game_defined_after_the_experiment_class_is_listed(registry):
    class Early(Experiment):
        timeline = Timeline(InfoPage("No game barrier.", time_estimate=5))

    class Late(LiveGame):
        name = "late"

    assert Early.realtime_games == [Late]
    assert object.__new__(Early).realtime_games == [Late]


def test_two_play_live_games_with_one_id_are_refused_when_the_experiment_loads(
    pair,
):
    class Twice(Experiment):
        test_mode = "parallel"
        test_n_bots = 2
        timeline = Timeline(
            _play("practice"),
            InfoPage("Now the real game.", time_estimate=5),
            _play("practice"),
        )

    with pytest.raises(
        RuntimeError, match="more than one PlayLiveGame with the id 'practice'"
    ):
        Twice.check_live_games()


def test_live_games_need_their_bots_to_play_together(pair):
    class Serial(Experiment):
        test_n_bots = 2
        timeline = Timeline(_play("together"))

    class Parallel(Serial):
        test_mode = "parallel"

    class Driven(Serial):
        def test_serial_run_bots(self, bots):
            pass

    with pytest.raises(RuntimeError, match='Set test_mode = "parallel"'):
        Serial.check_live_games()
    Parallel.check_live_games()
    Driven.check_live_games()


def test_a_subclass_with_its_parent_s_name_is_refused(registry):
    class Parent(LiveGame):
        name = "shared"

    with pytest.raises(ValueError, match="Parent and Child both use the name"):

        class Child(Parent):
            pass


def test_a_game_s_name_is_its_channel(registry):
    class Named(LiveGame):
        name = "named"

    class OldStyle(LiveGame):
        channel = "old_style"

    assert (Named.name, Named.channel) == ("named", "named")
    assert (OldStyle.name, OldStyle.channel) == ("old_style", "old_style")
    with pytest.raises(TypeError, match="Both sets both a name and a channel"):

        class Both(LiveGame):
            name = "both"
            channel = "other"


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

        class Game(LiveGame):
            messages = [Annotated]


def test_a_game_class_must_be_a_live_game_with_a_name_and_a_bot(
    registry,
):
    class Plain(RealtimeGame):
        channel = "plain"

    class Unnamed(LiveGame):
        def bot(self, view, player_id, now):
            return None

    class Botless(LiveGame):
        name = "botless"

    with pytest.raises(TypeError, match="game_class must be a LiveGame subclass"):
        _play("plain", game_class=Plain)
    with pytest.raises(TypeError, match="Unnamed has no name"):
        _play("unnamed", game_class=Unnamed)
    with pytest.raises(TypeError, match="Botless has no bot method"):
        _play("botless", game_class=Botless)


@pytest.mark.parametrize(
    "listed, error",
    [
        ([dict], "lists <class 'dict'>, which isn't a LiveMessage subclass"),
        ([NoType], "NoType.type must be a non-empty string"),
        ([NoApply], "NoApply must define apply"),
        ([Move, AlsoMove], "Move and AlsoMove both have the type 'move'"),
        (
            [PlayerReady],
            "lists PlayerReady, with the type 'psynet_ready', which is PsyNet's",
        ),
        (
            [PlayerReady, Move],
            "lists PlayerReady, with the type 'psynet_ready', which is PsyNet's",
        ),
    ],
)
def test_a_game_s_message_types_are_checked_when_it_is_defined(registry, listed, error):
    with pytest.raises((TypeError, ValueError), match=error):

        class Game(LiveGame):
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
        ({"1": (2, 3)}, {"1": [2, 3]}),
    ],
)
def test_the_state_is_converted_to_json_after_each_method_that_changes_it(
    registry, value, converted
):
    class Store(LiveGame):
        # A game for one, as the test plays it.
        away_timeout = None

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


def test_a_state_with_a_key_that_isnt_a_string_is_refused(registry):
    class Numbered(LiveGame):
        def initial_state(self, players):
            return {"scores": {player: 0 for player in players}}

        def view(self, state, player):
            return state

    # It would read back as "0" after a save, and state["scores"][0] would fail.
    with pytest.raises(ValueError, match="the key 0, of type int.*read back as '0'"):
        Numbered().initial_state(["3"])


def test_an_overridden_apply_is_converted(registry):
    class Overridden(LiveGame):
        messages = [Move]

        def initial_state(self, players):
            return {"moves": []}

        def view(self, state, player_id):
            return state

        def apply(self, state, player_id, message, now, sent):
            state["moves"].append(self.parse_message(message).to)

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

    class Timed(Timer, LiveGame):
        # A game for one, as the test plays it.
        away_timeout = None

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
    class Nested(LiveGame):
        def initial_state(self, players):
            return {"joins": []}

        def view(self, state, player):
            return state

        def tick(self, state, now):
            state["ticked"] = (now,)

        def on_join(self, state, player, now):
            joins = state["joins"]
            self.tick(state, now)
            joins.append((player, now))

    state = _started(joins=[])

    Nested().on_join(state, "1", 2)

    assert _game_part(state) == {"joins": [[0, 2]], "ticked": [2]}


def test_initial_state_keeps_its_references_while_it_calls_a_state_method(
    registry,
):
    class Joining(LiveGame):
        def initial_state(self, players):
            state = {"scores": []}
            scores = state["scores"]
            for player in players:
                self.on_join(state, player, None)
                scores.append((0,))
            return state

        def view(self, state, player):
            return state

        def on_join(self, state, player, now):
            state.setdefault("joined", []).append((player,))

    assert _game_part(Joining().initial_state(["1", "2"])) == {
        "scores": [[0], [0]],
        "joined": [[0], [1]],
    }


def test_a_game_that_inherits_apply_keeps_the_order_of_its_bases(registry):
    class Plain(LiveGame):
        messages = [Move]

        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return state

    class Logged(LiveGame):
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
    class Ticking(LiveGame):
        # A game for one, as the test plays it.
        away_timeout = None
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
    class Painting(LiveGame):
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
    class Converted(LiveGame):
        # A game for one, as the test plays it.
        away_timeout = None
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
    start_game(game, state)
    game.tick(state, 0)
    game.apply(state, "1", {"type": "move", "message": {"to": [2, 3]}}, 0, Sent())

    assert _game_part(state) == {
        "start": (0, 0),
        "ticked": (1, 1),
        "held": "tuple",
        "at": (2, 3),
    }


def test_a_state_that_can_t_be_converted_fails_loudly(registry):
    class Keep(LiveGame):
        # A game for one, as the test plays it.
        away_timeout = None

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

        class Game(LiveGame):
            messages = [Holds]


class Tap(LiveMessage):
    type = "tap"

    def apply(self, game, state, player, now):
        state["taps"].append([player, now])


TAP = {"type": "tap", "message": {}}


@pytest.fixture
def relay(registry):
    class Relay(LiveGame):
        # A game for one, as the test plays it.
        away_timeout = None
        name = "relay"
        messages = [Tap]
        ready_timeout = 10

        def initial_state(self, players):
            return {"taps": [], "ticks": []}

        def view(self, state, player):
            return {"taps": len(state["taps"])}

        def tick(self, state, now):
            state["ticks"].append(now)

        def next_deadline(self, state):
            return 99

        def on_start(self, state):
            state["deadline"] = 5

        def bot(self, view, player, now):
            return None if view["taps"] else Tap()

    return Relay()


def test_messages_are_rejected_until_every_player_is_ready(relay):
    state = relay.initial_state(["1", "2"])

    with pytest.raises(Reject) as rejected:
        relay.apply(state, "1", TAP, 1, Sent())
    for participant, now in [("1", 2), ("1", 3), ("2", 4)]:
        relay.apply(state, participant, READY, now, Sent())
    relay.apply(state, "1", TAP, 5, Sent())

    assert rejected.value.reason == NOT_STARTED
    assert state == {
        # Participant 1 is player 0, and the tap came 1 second into the game.
        "taps": [[0, 1]],
        "ticks": [],
        "deadline": 5,
        "psynet": _psynet(
            participant_ids=[1, 2], ready=[0, 1], started_at=4, ends_at=604
        ),
    }


def test_an_overridden_apply_gets_only_the_game_s_messages_after_the_start(relay):
    class Counted(type(relay)):
        name = "counted"

        def apply(self, state, player, message, now, sent):
            state["applied"] = state.get("applied", 0) + 1
            super().apply(state, player, message, now, sent)

    game = Counted()
    state = game.initial_state(["1"])

    with pytest.raises(Reject, match=NOT_STARTED):
        game.apply(state, "1", TAP, 1, Sent())
    game.apply(state, "1", READY, 2, Sent())
    game.apply(state, "1", TAP, 3, Sent())

    assert (state["applied"], state["taps"]) == (1, [[0, 1]])


def test_the_game_starts_at_the_ready_timeout_without_everyone(relay):
    state = relay.initial_state(["1", "2"])
    relay.apply(state, "1", READY, 1, Sent())

    assert relay.next_deadline(state) == 10
    relay.tick(state, 9.9)
    assert (state["psynet"]["started_at"], state["ticks"]) == (None, [])

    relay.tick(state, 10)
    assert state["psynet"] == _psynet(
        participant_ids=[1, 2], ready=[0], started_at=10, ends_at=610
    )
    # The game's clock starts at 0 when the game starts.
    assert (state["ticks"], state["deadline"]) == ([0], 5)
    # The game's deadline, 99 seconds into the game, on Dallinger's clock.
    assert relay.next_deadline(state) == 109
    relay.apply(state, "2", READY, 11, Sent())
    relay.apply(state, "2", TAP, 12, Sent())
    assert state["psynet"]["started_at"] == 10
    assert state["taps"] == [[1, 2]]


def advance(self, state, now):
    state["ticks"].append(now)


class Clock(RealtimeGame):
    def tick(self, state, now):
        state["ticks"].append(now)

    def next_deadline(self, state):
        return 99

    def on_leave(self, state, player, now):
        state["left"] = [player, now]


def test_the_ready_step_covers_renamed_methods_and_later_bases(relay):
    class Renamed(type(relay)):
        name = "renamed"
        tick = advance

    class Later(LiveGame, Clock):
        away_timeout = None
        name = "later"

        def initial_state(self, players):
            return {"ticks": []}

        def view(self, state, player):
            return {}

    for game in [Renamed(), Later()]:
        state = game.initial_state(["1"])
        game.tick(state, 1)
        game.apply(state, "1", READY, 2, Sent())
        game.tick(state, 3)

        assert state["ticks"] == [1], type(game).__name__
        assert game.next_deadline(state) == 101
    game.on_leave(state, "1", 4)
    assert state["left"] == [0, 2]


def test_a_game_can_build_on_another_game_s_state(relay):
    class Extended(type(relay)):
        name = "extended"

        def initial_state(self, players):
            return {**super().initial_state(players), "deadline": None}

    state = Extended().initial_state(["1"])

    assert state == {
        "taps": [],
        "ticks": [],
        "deadline": None,
        "psynet": _psynet(),
    }


def test_each_view_shows_who_is_ready_and_which_player_it_is_for(relay):
    state = relay.initial_state(["1", "2"])
    relay.apply(state, "2", READY, 1, Sent())

    # Without the participant ids, so a page can't tell who it plays with.
    entry = _psynet(participant_ids=[1, 2], ready=[1])
    del entry["participant_ids"]
    assert relay.view(state, "1") == {"taps": 0, "psynet": {**entry, "you": 0}}
    assert relay.view(state, "2")["psynet"]["you"] == 1


def test_a_game_calling_its_own_view_passes_the_player_s_number():
    class Scores(LiveGame):
        name = "scores"

        def initial_state(self, players):
            return {"scores": [10, 20], "seen": []}

        def view(self, state, player):
            return {"mine": state["scores"][player]}

        def tick(self, state, now):
            state["seen"] = [self.view(state, player)["mine"] for player in (0, 1)]

        def outcome(self, state, reason):
            return [self.view(state, player)["mine"] for player in (0, 1)]

        def bot(self, view, player, now):
            return None

    game = LocalGame(Scores, players=2)
    game.tick(1)

    assert game.state["seen"] == [10, 20]
    assert game.outcome() == [10, 20]


def test_a_game_with_an_away_timeout_ends_once_too_few_players_are_left():
    class Commons(LiveGame):
        name = "commons"
        min_players = 2
        away_timeout = 30

        def initial_state(self, players):
            return {}

        def view(self, state, player):
            return {}

        def bot(self, view, player, now):
            return None

    game = LocalGame(Commons, players=3)
    # Player 0 is gone at 40, which leaves enough players.
    game.leave(0, now=10)
    # Player 1 comes back in time, as after a reload, then leaves for good.
    game.leave(1, now=20)
    game.join(1, now=45)
    game.leave(1, now=50)
    # Dallinger ticks the game at its next deadline.
    assert game.game.next_deadline(game.state) == 80

    game.tick(79)
    assert not game.is_over()
    game.tick(80)
    assert game.is_over() == PLAYERS_LEFT


def test_by_default_a_game_for_two_ends_a_minute_after_one_player_leaves():
    class Pair(LiveGame):
        name = "pair_by_default"

        def initial_state(self, players):
            return {"left_alone": False}

        def view(self, state, player):
            return {}

        def bot(self, view, player, now):
            return None

    assert Pair.away_timeout == 60
    game = LocalGame(Pair, players=2)
    game.leave(1, now=5)
    game.tick(64)
    assert not game.is_over()
    game.tick(65)
    assert game.is_over() == PLAYERS_LEFT
    # And the outcome is the final state, without PsyNet's entry.
    assert game.outcome() == {"left_alone": False}


def test_a_game_s_join_timeout_is_its_ready_timeout(registry):
    class Quick(LiveGame):
        ready_timeout = 20

    assert Quick.join_timeout == 20
    with pytest.raises(TypeError, match="Set its ready_timeout instead"):

        class Slow(LiveGame):
            join_timeout = 90


def test_live_game_handles_every_hook_of_dallingers_game():
    # A new hook that gets a participant id or a session time needs
    # converting to a player number and the game's time before LiveGame
    # passes it on. Add it here once LiveGame handles it.
    hooks = {
        name
        for name, value in vars(RealtimeGame).items()
        if callable(value) and not name.startswith("_")
    }
    assert hooks == {
        "initial_state",
        "apply",
        "tick",
        "next_deadline",
        "view",
        "is_over",
        "outcome",
        "on_join",
        "on_leave",
        "on_add",
        "is_done",
        "save_message",
        "bot",
        "queue_effect",
        "handle_effect",
        "handle_ending",
        "handle_player_ending",
    }


def test_each_view_lists_the_players_who_have_left(relay):
    state = relay.initial_state(["1", "2", "3"])
    relay.on_join(state, "1", 0)
    relay.on_join(state, "2", 0)

    relay.on_leave(state, "2", 1)
    # Player 2, participant 3, hasn't joined yet, which isn't leaving.
    assert relay.view(state, "1")["psynet"]["away"] == [1]
    relay.on_join(state, "2", 2)
    assert relay.view(state, "1")["psynet"]["away"] == []


def test_a_player_who_leaves_before_the_start_is_not_ready(relay):
    state = relay.initial_state(["1", "2"])

    relay.apply(state, "1", READY, 1, Sent())
    relay.on_leave(state, "1", 2)
    relay.apply(state, "2", READY, 3, Sent())
    assert state["psynet"]["started_at"] is None
    relay.apply(state, "1", READY, 4, Sent())
    relay.on_leave(state, "1", 5)

    assert state["psynet"] == _psynet(
        participant_ids=[1, 2],
        ready=[1, 0],
        away=[0],
        away_since=[2, None],
        started_at=4,
        ends_at=604,
    )


def test_join_and_leave_get_no_time_before_the_game_starts(relay):
    class Logged(type(relay)):
        name = "logged"

        def on_join(self, state, player, now):
            state["ticks"].append(["join", player, now])

        def on_leave(self, state, player, now):
            state["ticks"].append(["leave", player, now])

    game = Logged()
    state = game.initial_state(["1"])
    game.on_join(state, "1", 1)
    game.apply(state, "1", READY, 2, Sent())
    game.on_leave(state, "1", 5)

    assert state["ticks"] == [["join", 0, None], ["leave", 0, 3]]


def test_a_game_method_that_calls_another_gets_the_ready_step(relay):
    class Eager(type(relay)):
        name = "eager"

        def on_join(self, state, player, now):
            self.tick(state, now)

    game = Eager()
    state = game.initial_state(["1"])

    game.on_join(state, "1", 1)

    assert state["ticks"] == []


CLOCK = 1.8e9


def _session_entry(kind, time, player_id, payload=None):
    """A session entry, as the web process adds it, for run_pass."""
    entry = {"type": kind, "time": time, "participant": player_id, "scope": "page"}
    if kind == "message":
        entry.update(data=json.dumps(payload), received=CLOCK + time)
    else:
        entry["socket"] = f"{player_id}/page"
    return entry


def test_a_deadline_due_by_the_ready_timeout_runs_when_the_game_starts(relay):
    class Overdue(type(relay)):
        name = "overdue"

        def next_deadline(self, state):
            return 0

        def is_over(self, state):
            return bool(state["ticks"])

    game = Overdue()
    entries = [
        _session_entry("join", 0, "1"),
        _session_entry("message", 1, "1", READY),
    ]

    waiting = run_pass(game, new_session(game, ["1", "2"]), entries, 2, CLOCK)
    ended = run_pass(game, waiting.saved, [], 10, CLOCK)

    assert waiting.next_due == 10
    assert ended.ended["reason"] == "finished"
    assert json.loads(ended.saved)["state"]["ticks"] == [0]


def test_the_testing_helper_starts_the_game(relay):
    state = relay.initial_state(["1", "2"])

    start_game(relay, state)

    assert state["psynet"]["ready"] == [0, 1]
    assert state["psynet"]["started_at"] == 0
    assert state["deadline"] == 5


def test_a_bot_plays_once_the_testing_helper_has_started_its_game():
    game = _pick_numbers()
    state = game.initial_state(["1", "2"])
    start_game(game, state)

    assert game.bot(game.view(state, "2"), "2", 0) == {
        "type": "pick",
        "message": {"number": 11},
    }


def test_an_on_start_that_ends_the_game_skips_its_tick(relay):
    class Everyone(type(relay)):
        name = "everyone"

        def on_start(self, state):
            entry = state["psynet"]
            state["everyone"] = len(entry["ready"]) == len(entry["participant_ids"])

        def is_over(self, state):
            return state.get("everyone") is False

    game = Everyone()
    entries = [
        _session_entry("join", 0, "1"),
        _session_entry("message", 1, "1", READY),
    ]

    waiting = run_pass(game, new_session(game, ["1", "2"]), entries, 2, CLOCK)
    ended = run_pass(game, waiting.saved, [], 10, CLOCK)

    assert ended.ended["reason"] == "finished"
    assert json.loads(ended.saved)["state"]["ticks"] == []


def test_a_game_with_a_duration_ends_when_its_time_is_up(relay):
    class Timed(type(relay)):
        name = "timed"
        duration = 20

    game = Timed()
    entries = [
        _session_entry("join", 0, "1"),
        _session_entry("message", 1, "1", READY),
    ]

    playing = run_pass(game, new_session(game, ["1"]), entries, 2, CLOCK)
    # A tick that runs late sees the end.
    ended = run_pass(game, playing.saved, [], 25, CLOCK)

    assert playing.next_due == 21
    assert ended.ended["reason"] == "finished"
    assert json.loads(ended.saved)["state"]["ticks"] == [20]


def test_a_game_without_a_duration_ends_at_its_timeout(relay):
    class Patient(type(relay)):
        name = "patient"
        timeout = 30

    game = Patient()
    entries = [
        _session_entry("join", 0, "1"),
        _session_entry("message", 1, "1", READY),
    ]

    playing = run_pass(game, new_session(game, ["1"]), entries, 2, CLOCK)
    ended = run_pass(game, playing.saved, [], 40, CLOCK)

    assert playing.next_due == 31
    assert ended.ended["reason"] == TIMEOUT
    # Without an outcome method, the outcome is the final state, without
    # PsyNet's entry.
    assert ended.ended["outcome"] == {"taps": [], "ticks": [30], "deadline": 5}
    assert Patient.max_duration == Patient.ready_timeout + 30 + 30


def test_a_game_with_a_duration_rejects_late_messages(relay):
    class Timed(type(relay)):
        name = "timed"
        duration = 20

    game = Timed()
    state = game.initial_state(["1"])
    game.apply(state, "1", READY, 1, Sent())
    game.apply(state, "1", TAP, 20.9, Sent())

    with pytest.raises(Reject, match="time is up"):
        game.apply(state, "1", TAP, 21, Sent())
    assert state["psynet"]["ends_at"] == 21
    assert state["psynet"]["duration"] == 20
    assert Timed.max_duration == Timed.ready_timeout + 20 + 30


@pytest.mark.parametrize(
    "attributes, error",
    [
        ({"duration": 0}, "Game's duration must be None or a positive number"),
        ({"timeout": "10"}, "Game's timeout must be None or a positive number"),
        ({"max_duration": 120}, "Game sets max_duration, which PsyNet sets"),
    ],
)
def test_a_duration_and_timeout_are_positive_and_max_duration_is_psynet_s(
    registry, attributes, error
):
    with pytest.raises((TypeError, ValueError), match=error):
        type("Game", (LiveGame,), attributes)


def test_a_game_without_a_duration_or_timeout_has_no_max_duration(registry):
    class Endless(LiveGame):
        timeout = None

    class Sub(Endless):
        pass

    assert (Endless.max_duration, Sub.max_duration) == (None, None)


def test_a_bot_is_ready_at_once_and_plays_once_the_game_starts(relay):
    state = relay.initial_state(["1", "2"])

    def bot_message(now):
        return relay.bot(relay.view(state, "1"), "1", now)

    assert bot_message(0) == READY
    with pytest.raises(ValueError, match="The view has no 'psynet' entry"):
        relay.bot({"taps": 0}, "1", 0)
    relay.apply(state, "1", READY, 0, Sent())
    assert bot_message(0) is None
    relay.apply(state, "2", READY, 1, Sent())
    assert bot_message(1) == TAP


@pytest.mark.parametrize(
    "state, view, error",
    [
        ([], {}, "Game.initial_state must return a dict, not list"),
        ({"psynet": 1}, {}, "a 'psynet' entry, which is PsyNet's"),
        ({}, [], "Game.view must return a dict, not list"),
        ({}, {"psynet": 1}, "Game.view returned a 'psynet' entry"),
    ],
)
def test_the_state_and_views_are_dicts_without_psynet_s_entry(
    registry, state, view, error
):
    class Game(LiveGame):
        def initial_state(self, players):
            return state

        def view(self, state, player):
            return view

    with pytest.raises((TypeError, ValueError), match=error):
        game = Game()
        game.view(game.initial_state(["1"]), "1")


@pytest.mark.parametrize("ready_timeout", [None, 0, -1, "30", float("inf")])
def test_a_ready_timeout_is_a_positive_number(registry, ready_timeout):
    with pytest.raises(ValueError, match="Game's ready_timeout must be a positive"):
        type("Game", (LiveGame,), {"ready_timeout": ready_timeout})


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
        "message": "The game isn't over yet. The page will move on once it is.",
        "retry_after": 1,
    }
    # A response the page sends again leaves nothing behind.
    assert (
        db.session.query(Response).filter_by(participant_id=members[0].id).count() == 0
    )
    assert LiveGameRecord(session_id).status == "running"
    assert LiveGameRecord(session_id).outcome is None

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
    # Each Pick's reward effect is handled as the record is written, and the
    # game's reward, the player's pick in hundredths, as its ending is saved,
    # so a player who never submits the page is paid too.
    assert _reward(members[0]) == pytest.approx(0.53)
    assert _reward(members[1]) == pytest.approx(0.55)

    assert _submit_on_the_game_page(members[0])["submission"] == "approved"
    assert _submit_on_the_game_page(members[0])["submission"] == "approved"

    outcome = [3, 5]
    game = LiveGameRecord(session_id)
    assert (game.status, game.end_reason, game.outcome, game.error) == (
        "ended",
        "finished",
        outcome,
        None,
    )
    assert game.participant_ids == sorted(member.id for member in members)
    assert game.record_complete
    assert _accepted_answers(members[0]) == [outcome, outcome]
    assert _reward(members[0]) == pytest.approx(0.53)
    # Later pages read the answer and the result through the participant.
    db.session.refresh(members[0])
    assert members[0].live_games["pick_numbers"].id == game.id
    assert members[0].live_games["pick_numbers"].finished
    assert members[0].live_games["pick_numbers"].answer == outcome
    assert members[0].live_game_history["pick_numbers"][-1].answer == outcome
    # Each player's answer, in player order, once their page has saved it.
    players = [game.participant_ids.index(member.id) for member in members]
    answers = [None, None]
    answers[players[0]] = outcome
    assert game.answers == answers
    assert members[0].live_games["pick_numbers"].player == players[0]
    # A record that isn't one participant's has no single answer.
    with pytest.raises(AttributeError, match="has no single answer"):
        game.answer
    # A trial's game is its participant's.
    group_round = SimpleNamespace(live_game_id=session_id)
    trial = SimpleNamespace(group_round=group_round, participant=members[0])
    assert Trial.live_game.fget(trial).answer == outcome
    assert Trial.live_game.fget(SimpleNamespace(group_round=None)) is None


def test_a_step_without_a_game_has_a_record_that_says_so(pair, monkeypatch):
    members, game_barrier = pair
    monkeypatch.setattr(type(_pick_numbers()), "min_players", 3)
    for member in members:
        _arrive(game_barrier, member)

    game = members[0].live_games[game_barrier.id]
    assert (game.id, game.status, game.finished) == (None, "not_started", False)
    assert (game.answer, game.outcome, game.end_reason, game.player) == (None,) * 4
    assert (game.messages, game.moments, game.participant_ids) == ([], [], [])
    assert not game.record_complete
    assert members[0].live_game_history[game_barrier.id] == []


def test_the_game_page_fails_once_its_game_can_no_longer_end(pair, monkeypatch):
    members, _ = pair
    session_id = _pair_session(pair)
    control = _game_page().control
    row = db.session.get(RealtimeSession, session_id)
    max_duration = _pick_numbers().max_duration

    def refusal_after(seconds):
        row.start_time = timenow() - datetime.timedelta(seconds=seconds)
        db.session.commit()
        return control.check_ready_for_response(get_experiment(), members[0])

    # Its ready timeout, its timeout and a margin, and a minute past those
    # for saving the result.
    assert max_duration == 60 + 60 + 30
    assert refusal_after(max_duration + 55).retry_after == 1
    with pytest.raises(
        RuntimeError,
        match=f"Live game {session_id} is still running after 21\\d seconds, "
        "though it should have ended by 150",
    ):
        refusal_after(max_duration + 65)

    # A game without a max_duration can run as long as it likes.
    monkeypatch.setattr(type(_pick_numbers()), "max_duration", None)
    assert refusal_after(max_duration + 65).retry_after == 1


@pytest.mark.parametrize(
    "end_reason, outcome, record_complete",
    [
        ("failed", [None, None], True),
        # The game's outcome raised an error too.
        ("failed", None, True),
        (None, None, False),
    ],
)
def test_a_failed_game_s_page_moves_on_with_what_was_saved(
    pair, end_reason, outcome, record_complete
):
    members, _ = pair
    session_id = _pair_session(pair)
    # How Dallinger saves a session that failed in the game's code, or one
    # whose record couldn't be written.
    db.session.query(RealtimeSession).filter_by(id=session_id).update(
        {
            "status": "failed",
            "end_reason": end_reason,
            "outcome": outcome,
            "error": "Traceback (most recent call last): ...",
        }
    )

    assert _submit_on_the_game_page(members[0])["submission"] == "approved"

    result = LiveGameRecord(session_id)
    assert result.record_complete is record_complete
    assert result.error == "Traceback (most recent call last): ..."
    assert _accepted_answers(members[0]) == [outcome]


@pytest.mark.parametrize(
    "status, outcome, paid",
    [
        ("failed", [None, None], True),
        # The game's outcome raised an error too.
        ("failed", None, False),
        # A game that doesn't define outcome ends with None.
        ("ended", None, True),
    ],
)
def test_the_ending_pays_each_player_s_reward_if_there_is_an_outcome(
    pair, monkeypatch, status, outcome, paid
):
    members, _ = pair
    session_id = _pair_session(pair)
    row = db.session.get(RealtimeSession, session_id)
    row.status, row.end_reason, row.outcome = status, "failed", outcome
    rewards = []
    game_class = game_registry._live_game_classes["pick_numbers"]
    # A game that computes rewards with NumPy returns a NumPy number.
    monkeypatch.setattr(
        game_class,
        "performance_reward",
        lambda self, *args: rewards.append(args) or numpy.float64(0.25),
    )

    game_class().handle_ending(row)

    # Each player's number, in the order PsyNet pays them.
    players = [
        [int(member) for member in row.members].index(participant.id)
        for participant in sorted(members, key=lambda member: member.id)
    ]
    assert rewards == (
        [(outcome, "failed", player) for player in players] if paid else []
    )
    assert [_reward(member) for member in members] == [0.25 if paid else 0] * 2


def test_the_game_page_answer_can_be_the_player_s_part_of_the_outcome(
    pair, monkeypatch
):
    members, _ = pair
    session_id = _pair_session(pair)
    db.session.query(RealtimeSession).filter_by(id=session_id).update(
        {
            "status": "ended",
            "end_reason": "finished",
            "outcome": ["first player's", "second player's"],
        }
    )
    game_class = game_registry._live_game_classes["pick_numbers"]
    monkeypatch.setattr(
        game_class,
        "answer",
        lambda self, outcome, reason, player: outcome[player],
    )
    first = min(members, key=lambda member: member.id)

    assert _submit_on_the_game_page(first)["submission"] == "approved"
    assert _accepted_answers(first) == ["first player's"]


@pytest.mark.parametrize("show_result_for", [0, 8])
def test_the_ending_copies_the_outcome_to_the_round_and_ends_the_game_page_deadline(
    pair, monkeypatch, show_result_for
):
    members, _ = pair
    monkeypatch.setattr(_game_page().control, "show_result_for", show_result_for)
    session_id = _pair_session(pair)
    group_round = SyncGroupRound(
        sync_group_id=members[0].sync_group_links[0].sync_group_id,
        module_id="game",
        number=0,
        live_game_id=session_id,
    )
    db.session.add(group_round)
    for member in members:
        member.waiting_barrier_id = None
        _game_page().consume(get_experiment(), member)
    row = db.session.get(RealtimeSession, session_id)
    row.status, row.end_reason = "ended", "finished"
    row.outcome = [4, 4]
    row.end_time = timenow()
    game_class = game_registry._live_game_classes["pick_numbers"]

    game_class().handle_ending(row)

    db.session.refresh(group_round)
    assert group_round.live_game_outcome == row.outcome
    # So a later barrier's late_after counts from when the page stops showing
    # the result.
    shown_until = row.end_time + datetime.timedelta(seconds=show_result_for)
    assert [m.sync_group_links[0].page_deadline for m in members] == [shown_until] * 2


def test_a_game_page_without_a_game_moves_on_with_no_answer(pair):
    members, _ = pair

    assert _submit_on_the_game_page(members[0])["submission"] == "approved"
    assert _accepted_answers(members[0]) == [None]


def test_a_game_record_needs_a_game(db_session):
    with pytest.raises(KeyError):
        LiveGameRecord(12345).status


@pytest.mark.parametrize("amount", [-1, "1"])
def test_a_reward_is_a_number_0_or_more(pair, monkeypatch, amount):
    members, _ = pair
    session_id = _pair_session(pair)
    db.session.query(RealtimeSession).filter_by(id=session_id).update(
        {"status": "ended", "end_reason": "finished", "outcome": {}}
    )
    game_class = game_registry._live_game_classes["pick_numbers"]
    monkeypatch.setattr(game_class, "performance_reward", lambda self, *args: amount)

    with pytest.raises(
        ValueError, match=f"PickNumbers.performance_reward gave the reward {amount!r}"
    ):
        game_class().handle_ending(db.session.get(RealtimeSession, session_id))
    with pytest.raises(
        ValueError, match="PickNumbers.add_performance_reward gave the reward"
    ):
        game_class().add_performance_reward(0, amount)


def test_a_game_s_own_handle_effect_gets_its_effects_but_not_its_rewards(pair):
    members, _ = pair
    session_id = _pair_session(pair)
    handled = []

    class Scored(LiveGame):
        def initial_state(self, players):
            return {}

        def view(self, state, player_id):
            return {}

        def handle_effect(self, name, payload, session_row):
            handled.append(name)

    effects = []
    token = queued_effects.set(effects)
    try:
        # Player 0, the participant with the lower id.
        Scored().add_performance_reward(0, 0.5)
        Scored().add_performance_reward(0, numpy.int64(1))
        Scored().add_performance_reward(0, 0)
        Scored().queue_effect("scored", {})
        for not_a_player in ["0", -1, True]:
            with pytest.raises(TypeError, match="needs a player's number"):
                Scored().add_performance_reward(not_a_player, 1)
    finally:
        queued_effects.reset(token)
    assert [name for name, _ in effects] == [
        "psynet_performance_reward",
        "psynet_performance_reward",
        "scored",
    ]
    row = db.session.get(RealtimeSession, session_id)
    for name, payload in effects:
        Scored().handle_effect(name, payload, row)

    first = min(members, key=lambda member: member.id)
    assert handled == ["scored"]
    assert _reward(first) == pytest.approx(1.5)
    with pytest.raises(ValueError, match="player 2, but game .* has only 2"):
        Scored().handle_effect(
            "psynet_performance_reward", {"player": 2, "amount": 1}, row
        )
    with pytest.raises(
        ValueError, match="'psynet_performance_reward' is reserved for PsyNet's"
    ):
        Scored().queue_effect("psynet_performance_reward", {})


class ValidatingPage(ModularPage):
    def validate(self, response, **kwargs):
        return None


@pytest.mark.parametrize(
    "page_type, kwargs",
    [(ModularPage, {"validate": lambda response: None}), (ValidatingPage, {})],
)
def test_a_live_game_page_can_t_have_a_validate_of_its_own(page_type, kwargs):
    with pytest.raises(TypeError, match="LiveGameControl and a validate function"):
        page_type("game", "Play", LiveGameControl(), **kwargs)


class Shot(LiveMessage):
    type = "shot"
    at: int

    def apply(self, game, state, player_id, now):
        if self.at < 0:
            raise Reject("Aim at the board.")
        state["hits"] += self.at == state["target"]

    def should_save(self, game, state, player_id, rejection):
        return rejection is not None


@pytest.fixture
def range_game(registry):
    class Range(LiveGame):
        name = "range"
        messages = [Shot]

        def initial_state(self, players):
            return {"target": 3, "hits": 0}

        def view(self, state, player_id):
            return {}

        def bot(self, view, player_id, now):
            return None

    return Range()


def _shot(at):
    return {"type": "shot", "message": {"at": at}}


@pytest.mark.parametrize("at, saved", [(3, False), (-1, True)])
def test_a_message_s_should_save_decides_whether_it_is_saved(range_game, at, saved):
    state = _started(target=3, hits=0)
    message = _shot(at)
    rejection = None
    # As Dallinger does: apply, then save_message with a copy of the message.
    try:
        range_game.apply(state, "1", message, 0, Sent())
    except Reject as raised:
        rejection = raised
    assert range_game.save_message(state, "1", dict(message), rejection) is saved


def test_a_message_the_game_couldn_t_read_is_saved(range_game):
    state = _started(target=3, hits=0)
    message = {"type": "shot", "message": {"at": "near"}}
    with pytest.raises(Reject) as rejection:
        range_game.apply(state, "1", message, 0, Sent())
    assert range_game.save_message(state, "1", message, rejection.value) is True


def test_psynet_s_ready_messages_are_saved_whatever_the_game_says(registry):
    class Quiet(LiveGame):
        name = "quiet"
        messages = [Shot]

        def initial_state(self, players):
            return {"target": 3}

        def view(self, state, player_id):
            return {}

        def save_message(self, state, player_id, message, rejection):
            return False

        def bot(self, view, player_id, now):
            return None

    state = _started(target=3)
    assert Quiet().save_message(state, "1", READY, None) is True
    assert Quiet().save_message(state, "1", _shot(3), None) is False


@pytest.mark.parametrize("max_players", [0, 1, 2.0, True])
def test_max_players_must_be_a_whole_number_of_at_least_min_players(
    registry, max_players
):
    with pytest.raises(ValueError, match="max_players must be None or a whole"):
        # Defining the subclass checks it.
        type("TooFew", (LiveGame,), {"max_players": max_players})


def test_a_group_larger_than_the_game_s_max_players_starts_no_game(
    pair, monkeypatch, caplog
):
    members, game_barrier = pair
    monkeypatch.setattr(type(_pick_numbers()), "min_players", 1)
    monkeypatch.setattr(type(_pick_numbers()), "max_players", 1)

    # Not an error, which would leave the group waiting at the barrier.
    for member in members:
        _arrive(game_barrier, member)

    assert _game_id(members[0], game_barrier.id) is None
    assert "has a max_players of 1" in caplog.text


def test_a_game_numbers_its_players_in_seat_order(pair, monkeypatch):
    members, game_barrier = pair
    group = members[0].active_sync_groups["pair"]
    (first,) = [
        link for link in group.participant_links if link.participant_id == members[0].id
    ]
    first.admitted_at += datetime.timedelta(seconds=1)
    started = []
    monkeypatch.setattr(
        "psynet.live_game.play.create_realtime_session",
        lambda game_class, players, bots=(): started.append(players) or 1,
    )

    game_barrier._start_session(members, group)

    assert started == [[members[1].id, members[0].id]]


def _growing_picks():
    return sys.modules[type(get_experiment()).__module__].GrowingPicks


def test_a_player_added_to_a_game_gets_the_next_number_and_can_finish_first():
    game = LocalGame(_growing_picks(), players=2)

    assert game.add(now=1) == 2
    game.send(2, _pick(4))

    assert game.is_done(2) and not game.is_done(0)
    with pytest.raises(Reject, match="Your game has ended"):
        game.send(2, _pick(5))
    assert game.answer(2) == [None, None, 4]


def test_players_whose_game_has_ended_leave_too_few_for_the_game(monkeypatch):
    growing = _growing_picks()
    monkeypatch.setattr(growing, "away_timeout", 30)
    monkeypatch.setattr(growing, "min_players", 2)
    game = LocalGame(growing, players=3)

    game.leave(1, now=5)
    # With three players, the game can lose one, so it goes on to its timeout.
    assert game.game.next_deadline(game.state) == 60
    game.send(0, _pick(3))
    # Players 1 and 2 still play, so it ends once player 1 has been away
    # for its away_timeout.
    assert game.game.next_deadline(game.state) == 5 + 30
    game.send(2, _pick(4))
    # Player 1 alone is too few at once.
    assert game.game.next_deadline(game.state) == 0


def test_a_newcomer_joins_the_group_s_running_game_and_finishes_before_it(
    db_session,
):
    experiment = get_experiment()
    members = [new_participant(experiment) for _ in range(3)]
    group = SimpleSyncGroup(
        group_type="pair",
        initial_group_size=2,
        max_group_size=3,
        quorum=1,
        n_active_participants=2,
        below_quorum="continue_without_group",
    )
    db_session.add(group)
    for member in members[:2]:
        member.status = "working"
        group.add_participant(member)
    group.leader = members[0]
    db_session.commit()
    with pytest.raises(TypeError, match="has no on_add method"):
        _play(join_running_game=True)
    page = ModularPage("growing", "Play.", LiveGameControl(), time_estimate=5)
    barrier = _play(
        "growing", page, game_class=_growing_picks(), join_running_game=True
    ).barrier
    for member in members[:2]:
        _arrive(barrier, member)
    session_id = _game_id(members[0], "growing")

    members[2].status = "working"
    group.add_participant(members[2])
    _reach(barrier, members[2])
    db.session.commit()

    assert _game_id(members[2], "growing") == session_id
    assert group.running_live_games == {"growing": LiveGameRecord(session_id)}
    group_id = group.id
    first, second, newcomer = (str(member.id) for member in members)
    _play_to_the_end(
        session_id,
        [
            (first, 1, READY),
            (second, 1, READY),
            (newcomer, 1, READY),
            (first, 2, {"type": "pick", "message": {"number": 3}}),
            (newcomer, 2, {"type": "pick", "message": {"number": 4}}),
            (second, 2, {"type": "pick", "message": {"number": 5}}),
        ],
    )

    members = [
        db.session.get(Participant, int(member)) for member in (first, second, newcomer)
    ]
    assert _session_participant_ids(session_id) == [m.id for m in members]
    assert db.session.get(SimpleSyncGroup, group_id).running_live_games == {}
    # Each player is paid once, from the outcome when their own game ended.
    assert [_reward(m) for m in members] == pytest.approx([0.03, 0.05, 0.04])
    answers = []
    for member in members:
        response = SimpleNamespace(answer=None)
        page.control.validate(response, member)
        answers.append(response.answer)
    assert answers == [[3, None, None], [3, 5, 4], [3, None, 4]]
    game = members[2].live_games["growing"]
    ((joined),) = game.moments
    # Added before the game started.
    assert (joined.name, joined.data, joined.time < 0) == (
        "joined",
        {"player": 2},
        True,
    )
    assert game.checkpoints[-1].state == {
        "picks": [3, 5, 4],
        "pick_reward": 0,
    }
