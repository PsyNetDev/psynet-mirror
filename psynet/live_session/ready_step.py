"""The ready step: a session starts once every player is ready, or at the
game's ready_timeout."""

from dallinger.realtime import Reject

from .messages import LiveMessage, _parse_message


class Ready(LiveMessage):
    """The message that says a player is ready to play. A game page sends it
    by itself once it has measured its clock against the server's, and a
    bot sends it at once. The session starts when every player is ready, or
    at the game's :attr:`~LiveSession.ready_timeout`.

    Every game reads it, so don't list it in a game's
    :attr:`~LiveSession.messages`. ``Ready.saved_messages(session_id)``
    returns when each player became ready.
    """

    type = "psynet_ready"

    def apply(self, game, state, player_id, now):
        """Mark the player ready, and start the session once every player
        is."""
        ready_step = _ready_step(state)
        if player_id not in ready_step["ready"]:
            ready_step["ready"].append(player_id)
        if set(ready_step["players"]) <= set(ready_step["ready"]):
            game.start_session(state, now)


# Documented in docs/reference/api/live_session.rst, since Sphinx doesn't
# read a comment on a re-exported constant.
NOT_STARTED = "The game hasn't started yet."


def _ready_step(state, what="state"):
    try:
        return state["live_session"]
    except (KeyError, TypeError):
        raise ValueError(
            f"The {what} has no 'live_session' entry, which PsyNet adds to the "
            "state initial_state returns, and to each view. Start from those."
        ) from None


def _apply_once_started(self, method, state, player_id, message, now, sent):
    if isinstance(message, dict) and message.get("type") == Ready.type:
        _parse_message(self._message_types, message).apply(self, state, player_id, now)
        return None
    if _ready_step(state)["started_at"] is None:
        raise Reject(NOT_STARTED)
    return method(self, state, player_id, message, now, sent)


def _tick_once_started(self, method, state, now):
    if _ready_step(state)["started_at"] is None:
        if self.ready_timeout is None or now < self.ready_timeout:
            return _UNCHANGED
        self.start_session(state, now)
        # Dallinger counts this tick as run, so a deadline due by now gets
        # no other.
        if self.is_over(state):
            return None
    return method(self, state, now)


def _leave_unready(self, method, state, player_id, now):
    ready_step = _ready_step(state)
    if ready_step["started_at"] is None and player_id in ready_step["ready"]:
        ready_step["ready"].remove(player_id)
    return method(self, state, player_id, now)


def _add_ready_step(self, method, players):
    state = method(self, players)
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
    state["live_session"] = {"players": list(players), "ready": [], "started_at": None}
    return state


# Returned by an entry in _READY_STEP that left the state as it was, so it
# isn't converted.
_UNCHANGED = object()


# The ready step's part of a state method, which runs in its place.
_READY_STEP = {
    "apply": _apply_once_started,
    "tick": _tick_once_started,
    "on_leave": _leave_unready,
    "initial_state": _add_ready_step,
}
