"""The wrappers LiveGame puts around a game's methods: the state's
conversion to JSON, the ready step and the game's duration."""

import contextvars
import functools

from dallinger.realtime import Reject
from pydantic_core import to_jsonable_python

from .messages import LiveMessage
from .psynet_entry import (
    _SESSION_BOOKKEEPING,
    _UNCHANGED,
    PLAYERS_LEFT,
    TIMEOUT,
    PlayerReady,
    _game_time,
    _player,
    _psynet_entry,
    _too_few_players_at,
)

# The game methods that can change the state, which is converted after each.
_STATE_METHODS = ("apply", "tick", "on_join", "on_leave", "on_add", "on_start")

# The game methods that get neither a participant id nor a session time.
_GAME_CODE_METHODS = ("outcome", "answer", "performance_reward")


# Set while the game's own code runs. A call it makes to another of the
# game's methods, directly or through super(), already has the player's
# number and the game's time, so it passes them through unconverted, and a
# state method converts the state once, after the outermost call.
# Converting rebuilds every dict and list in the state, which would cut off
# references the outer call still holds.
_in_game_code = contextvars.ContextVar("_in_game_code", default=False)


def _as_game_code(call, *args, **kwargs):
    """Return ``call(*args, **kwargs)``, run with ``_in_game_code`` set."""
    if _in_game_code.get():
        return call(*args, **kwargs)

    # In a copy of the context, so nothing has to unset the flag, even when
    # Dallinger's time limit interrupts the call.
    def run():
        _in_game_code.set(True)
        return call(*args, **kwargs)

    return contextvars.copy_context().run(run)


def _runs_game_code(method):
    """Wrap a method that neither gets a participant id nor a session time,
    so that calls it makes to the game's other methods aren't converted."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return _as_game_code(method, self, *args, **kwargs)

    wrapper._psynet_wrapper = True
    return wrapper


def _converts_outermost_call(method, name, convert):
    """Wrap the state method ``name`` so that ``convert(self, result, args)``
    runs after the outermost call only, and each call to the game's ``name``,
    as opposed to a ``super()`` call, goes through its entry in
    ``_SESSION_BOOKKEEPING``, if it has one."""
    session_part = _SESSION_BOOKKEEPING.get(name)

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        outermost = not _in_game_code.get()
        if session_part is not None and getattr(type(self), name) is wrapper:
            call = functools.partial(session_part, self, method, outermost)
        else:
            call = functools.partial(method, self)
        result = _as_game_code(call, *args, **kwargs)
        if result is _UNCHANGED:
            return None
        if not outermost:
            return result
        if not self.convert_state_to_json:
            return result
        return convert(self, result, args)

    wrapper._psynet_wrapper = True
    return wrapper


def _stores_json(method, name=None):
    name = name or method.__name__

    def convert_in_place(self, result, args):
        state = args[0]
        converted = _to_json(state, f"{type(self).__name__}.{name}")
        # Changed in place, since Dallinger keeps the state object.
        state.clear()
        state.update(converted)

    return _converts_outermost_call(method, name, convert_in_place)


def _reads_state(method, name):
    """Wrap a method that only reads the state, such as ``is_done``, so
    that its outermost call goes through its entry in
    ``_SESSION_BOOKKEEPING``."""
    return _converts_outermost_call(method, name, lambda self, result, args: result)


def _returns_json(method, name):
    def convert_returned(self, state, args):
        return _to_json(state, f"{type(self).__name__}.{name}")

    return _converts_outermost_call(method, name, convert_returned)


def _waits_for_start(method):
    @functools.wraps(method)
    def next_deadline(self, state):
        if _in_game_code.get():
            return method(self, state)
        entry = _psynet_entry(state)
        if entry["started_at"] is None:
            return self.ready_timeout
        deadline = _as_game_code(method, self, state)
        if deadline is not None:
            # On the game's clock, as the game's other methods see it.
            deadline += entry["started_at"]
        deadlines = [deadline, _too_few_players_at(self, state)]
        if not entry["time_up"]:
            deadlines.append(entry["ends_at"])
        return min((d for d in deadlines if d is not None), default=None)

    next_deadline._psynet_wrapper = True
    return next_deadline


def _ends_when_time_is_up(method):
    @functools.wraps(method)
    def is_over(self, state):
        entry = _psynet_entry(state)
        # A string is Dallinger's reason for the end.
        if entry["time_up"]:
            return "finished" if self.duration is not None else TIMEOUT
        if entry["players_left"]:
            return PLAYERS_LEFT
        return _as_game_code(method, self, state)

    is_over._psynet_wrapper = True
    return is_over


def _shows_psynet_entry(method):
    @functools.wraps(method)
    def view(self, state, player_id):
        if _in_game_code.get():
            return method(self, state, player_id)
        entry = _psynet_entry(state)
        player = _player(entry, player_id)
        shown = _as_game_code(method, self, state, player)
        if not isinstance(shown, dict):
            raise TypeError(
                f"{type(self).__name__}.view must return a dict, not "
                f"{type(shown).__name__}."
            )
        # A view can be the state itself.
        if shown.get("psynet", entry) != entry:
            raise ValueError(
                f"{type(self).__name__}.view returned a 'psynet' entry, "
                "which is PsyNet's. Give it another name."
            )
        # Pages get player numbers only, so no player learns another's
        # participant id, and with it who they've played before.
        public = {
            key: value for key, value in entry.items() if key != "participant_ids"
        }
        return {**shown, "psynet": {**public, "you": player}}

    view._psynet_wrapper = True
    return view


def _sends_message(method):
    @functools.wraps(method)
    def send(self, view, player_id, now):
        outermost = not _in_game_code.get()
        if outermost:
            entry = _psynet_entry(view, "view")
            # The view is the bot's own, so it says which player the bot is.
            player_id = entry["you"]
            if player_id not in entry["ready"]:
                return {"type": PlayerReady.type, "message": {}}
            if entry["started_at"] is None:
                return None
            now = _game_time(entry, now)
        message = _as_game_code(method, self, view, player_id, now)
        # A bot calling super().bot() reaches its parent's wrapper, which
        # leaves the message for the outermost one.
        if not outermost or not isinstance(message, LiveMessage):
            return message
        sent = {
            "type": message.type,
            "message": message.model_dump(mode="json", by_alias=True),
        }
        # No page sees a bot's rejections, so a message the game can't read
        # fails the game here.
        try:
            read = self.parse_message(sent)
        except Reject as rejection:
            problem = rejection.reason
        else:
            if read == message:
                return sent
            problem = f"It reads back as {read!r}."
        raise TypeError(
            f"{type(self).__name__}.bot returned {message!r}, which the game "
            f"can't read as it is. {problem} A bot can also return what a page "
            "sends, as a dict."
        )

    send._psynet_wrapper = True
    return send


def _to_json(state, what):
    key = _non_string_key(state)
    if key is not None:
        raise ValueError(
            f"After {what}, the state has a dict with the key {key!r}, of type "
            f"{type(key).__name__}. The state is saved as JSON, whose keys are "
            f"strings, so after a save the key would read back as {str(key)!r} "
            "and looking it up would fail. Use string keys, or keep what each "
            "player has in a list, in player order."
        )
    try:
        return to_jsonable_python(state)
    except (ValueError, TypeError) as error:
        raise ValueError(
            f"After {what}, the state holds a value PsyNet can't convert to "
            f"JSON. {error}."
        ) from None


def _non_string_key(value, seen=None):
    """Return the first dict key in ``value`` that isn't a string, or None."""
    if isinstance(value, (dict, list, tuple)):
        seen = set() if seen is None else seen
        # A value that contains itself is left for the conversion to report.
        if id(value) in seen:
            return None
        seen.add(id(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return key
            found = _non_string_key(item, seen)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _non_string_key(item, seen)
            if found is not None:
                return found
    return None


def _saves_ready_messages(method):
    """Save PsyNet's own messages, such as PlayerReady, whatever the game's
    save_message says, since the record needs them to show when each player
    became ready."""

    @functools.wraps(method)
    def save_message(self, state, player_id, message, rejection):
        if _in_game_code.get():
            return method(self, state, player_id, message, rejection)
        if isinstance(message, dict) and message.get("type") == PlayerReady.type:
            return True
        player = _player(_psynet_entry(state), player_id)
        return _as_game_code(method, self, state, player, message, rejection)

    save_message._psynet_wrapper = True
    return save_message
