"""PsyNet's part of a game's state, the ``state["live_session"]`` entry that
_live_session_entry returns, and the wrappers that keep it up to date.

The ready step: the game starts once every player is ready, or at the
game's ready_timeout. Once it starts, a game with a duration rejects
messages from its end, and the entry also keeps track of which players have
left."""

import contextvars

from dallinger.realtime import Reject

from .messages import LiveMessage, _parse_message

# The settings of the session a PlayLiveGame is starting, set
# while it calls create_realtime_session, which calls the game's
# initial_state before it returns.
_new_session_settings = contextvars.ContextVar("_new_session_settings", default=None)


class PlayerReady(LiveMessage):
    """The message that says a player is ready to play. A game page sends it
    by itself a moment after it opens, once it has checked the server's time,
    and a bot sends it at once. The game starts when every player is
    ready, or at the game's :attr:`~LiveGame.ready_timeout`.

    Every game reads it, so don't list it in a game's
    :attr:`~LiveGame.messages`. PsyNet handles it before the game's
    ``apply``, so the game never receives it, even in an ``apply`` of its
    own. A game reads who is ready from ``state["live_session"]["ready"]``,
    and reacts to the game starting in :meth:`~LiveGame.on_start`.
    ``PlayerReady.saved_messages(session_id)`` returns when each player became
    ready.
    """

    type = "psynet_ready"

    def apply(self, game, state, player_id, now):
        """Mark the player ready, and start the session once every player
        is."""
        entry = _live_session_entry(state)
        if player_id not in entry["ready"]:
            entry["ready"].append(player_id)
        if set(entry["players"]) <= set(entry["ready"]):
            game._end_ready_step(state, now)


# Documented in docs/reference/api/live_session.rst, since Sphinx doesn't
# read a comment on a re-exported constant.
NOT_STARTED = "The game hasn't started yet."

_TIME_UP = "The game's time is up."


def _live_session_entry(state, what="state"):
    try:
        return state["live_session"]
    except (KeyError, TypeError):
        raise ValueError(
            f"The {what} has no 'live_session' entry, which PsyNet adds to the "
            "state initial_state returns, and to each view. Start from those."
        ) from None


def _apply_once_started(self, method, state, player_id, message, now, sent):
    if isinstance(message, dict) and message.get("type") == PlayerReady.type:
        _parse_message(self._message_types, message).apply(self, state, player_id, now)
        return None
    entry = _live_session_entry(state)
    if entry["started_at"] is None:
        raise Reject(NOT_STARTED)
    if entry["ends_at"] is not None and now >= entry["ends_at"]:
        raise Reject(_TIME_UP)
    return method(self, state, player_id, message, now, sent)


def _tick_once_started(self, method, state, now):
    if _live_session_entry(state)["started_at"] is None:
        if self.ready_timeout is None or now < self.ready_timeout:
            return _UNCHANGED
        self._end_ready_step(state, now)
        # Dallinger counts this tick as run, so a deadline due by now gets
        # no other.
        if self.is_over(state):
            return None
    ends_at = _live_session_entry(state)["ends_at"]
    if ends_at is None or now < ends_at:
        return method(self, state, now)
    # A tick that runs late sees the end, so the game counts nothing after it.
    result = method(self, state, ends_at)
    _live_session_entry(state)["time_up"] = True
    return result


def _record_leave(self, method, state, player_id, now):
    entry = _live_session_entry(state)
    if entry["started_at"] is None and player_id in entry["ready"]:
        entry["ready"].remove(player_id)
    if player_id not in entry["away"]:
        entry["away"].append(player_id)
    return method(self, state, player_id, now)


def _record_join(self, method, state, player_id, now):
    # A game's initial_state can call on_join before PsyNet adds its entry.
    entry = state.get("live_session") if isinstance(state, dict) else None
    if entry is not None and player_id in entry["away"]:
        entry["away"].remove(player_id)
    return method(self, state, player_id, now)


def _add_live_session_entry(self, method, players, *settings):
    # Dallinger calls initial_state with the players alone, so a
    # PlayLiveGame's settings come from _new_session_settings.
    if not settings and _new_session_settings.get() is not None:
        settings = (_new_session_settings.get(),)
    state = method(self, players, *settings)
    name = type(self).__name__
    if not isinstance(state, dict):
        raise TypeError(
            f"{name}.initial_state must return a dict, not {type(state).__name__}."
        )
    if "live_session" in state:
        raise ValueError(
            f"{name}.initial_state returned a state with a 'live_session' entry, "
            "which is PsyNet's. Give it another name."
        )
    state["live_session"] = {
        "players": list(players),
        "ready": [],
        "started_at": None,
        "ends_at": None,
        "time_up": False,
        "away": [],
    }
    return state


# Returned by an entry in _SESSION_BOOKKEEPING that left the state as it
# was, so it isn't converted.
_UNCHANGED = object()


# PsyNet's part of each state method, which keeps the live_session entry up
# to date and runs in the method's place, calling the game's own method.
_SESSION_BOOKKEEPING = {
    "apply": _apply_once_started,
    "tick": _tick_once_started,
    "on_leave": _record_leave,
    "on_join": _record_join,
    "initial_state": _add_live_session_entry,
}
