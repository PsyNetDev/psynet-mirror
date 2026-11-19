"""PsyNet's part of a game's state, the ``state["psynet"]`` entry that
_psynet_entry returns, and the wrappers that keep it up to date.

The ready step: the game starts once every player is ready, or at the
game's ready_timeout. Once it starts, the game ends at its duration or its
time limit, and rejects messages from then on. The entry also keeps track of
which players are away, and since when, so that a game with an
away_timeout can end once too few players are left. A player added while
the game runs gets the next number, and players whose game has ended, by
the game's is_done, don't count towards min_players. ``last_event``, the
time of the latest event the game handled, is when a started game ended,
unless Dallinger's max_duration, which is only a safety net, ended it. Ending
jobs and final views read absences at that time, so they agree on who didn't
play.

The game's clock: Dallinger's session clock starts when the game is
created, before the ready step, but the game's methods get ``now`` in
seconds since the game started, which these wrappers convert to. The entry's
``started_at`` and ``ends_at`` are on Dallinger's clock."""

import contextvars

from dallinger.realtime import Reject

from .messages import LiveMessage, _parse_message
from .record import _game_time

# The settings of the game a PlayLiveGame is starting, set
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
    own. A game reads who is ready from ``state["psynet"]["ready"]``,
    which also lists the players added once the game has started,
    and reacts to the game starting in :meth:`~LiveGame.on_start`.
    A game record's :attr:`~LiveGameRecord.messages` include when each
    player who was there when the game started became ready. Players
    added once the game has started already count as ready, so bots added
    then, and newcomers who never open the game page, don't send it, but a
    newcomer's game page still sends it when it connects.
    """

    type = "psynet_ready"

    def apply(self, game, state, player, now):
        """Mark the player ready, and start the game once every player
        is."""
        entry = _psynet_entry(state)
        if player not in entry["ready"]:
            entry["ready"].append(player)
        if len(entry["ready"]) == len(entry["participant_ids"]):
            game._end_ready_step(state, now)


# Documented in docs/reference/api/live_game.rst, since Sphinx doesn't
# read a comment on a re-exported constant.
NOT_STARTED = "The game hasn't started yet."

_TIME_UP = "The game's time is up."

#: The reason a game ends with when it reaches its
#: :attr:`~LiveGame.timeout`.
TIMEOUT = "timeout"

#: The reason a game with an :attr:`~LiveGame.away_timeout` ends with when
#: too few players are left.
PLAYERS_LEFT = "players_left"


def _psynet_entry(state, what="state"):
    try:
        return state["psynet"]
    except (KeyError, TypeError):
        raise ValueError(
            f"The {what} has no 'psynet' entry, which PsyNet adds to the "
            "state initial_state returns, and to each view. Start from those."
        ) from None


def _player(entry, player_id):
    """Return the number of the player whose participant id Dallinger gave,
    as the game's methods see it."""
    return entry["participant_ids"].index(int(player_id))


# Each of these takes ``outermost``: whether Dallinger called the method, so
# that it has a participant id and a session time to convert, rather than the
# game's own code, which already has the player's number and the game's time.


def _apply_once_started(self, method, outermost, state, player_id, message, now, sent):
    entry = _psynet_entry(state)
    player = _player(entry, player_id) if outermost else player_id
    if outermost:
        entry["last_event"] = now
    is_ready = isinstance(message, dict) and message.get("type") == PlayerReady.type
    if outermost and is_ready:
        _parse_message(self._message_types, message).apply(self, state, player, now)
        return None
    if entry["started_at"] is None:
        raise Reject(NOT_STARTED)
    game_now = _game_time(entry["started_at"], now) if outermost else now
    end = _game_end(entry)
    if end is not None and game_now >= end:
        raise Reject(_TIME_UP)
    return method(self, state, player, message, game_now, sent)


def _tick_once_started(self, method, outermost, state, now):
    entry = _psynet_entry(state)
    if entry["started_at"] is None and (not outermost or now < self.ready_timeout):
        return _UNCHANGED
    if outermost:
        # Dallinger runs no tick for a deadline at or before its last tick.
        # Recorded before the tick_rate == 0 start path below returns, which
        # also counts as a tick, or next_deadline keeps a handled deadline.
        entry["last_tick"] = entry["last_event"] = now
    if entry["started_at"] is None:
        self._end_ready_step(state, now)
        # Dallinger counts this tick as run, so a deadline due by now gets
        # no other.
        if self.is_over(state):
            return None
        if not self.tick_rate:
            # A game without ticks runs its tick only at its deadlines, and
            # its clock is at 0.
            deadline = self.next_deadline(state)
            if deadline is None or deadline > 0:
                return None
    if outermost:
        too_few_at = _too_few_players_at(self, state)
        if too_few_at is not None and now >= too_few_at:
            entry["players_left"] = True
            return None
    game_now = _game_time(entry["started_at"], now) if outermost else now
    end = _game_end(entry)
    if end is None or game_now < end:
        return method(self, state, game_now)
    # A tick that runs late sees the end, so the game counts nothing after it.
    result = method(self, state, end)
    entry["time_up"] = True
    return result


def _record_leave(self, method, outermost, state, player_id, now):
    entry = _psynet_entry(state)
    if not outermost:
        return method(self, state, player_id, now)
    player = _player(entry, player_id)
    entry["last_event"] = now
    if entry["started_at"] is None and player in entry["ready"]:
        entry["ready"].remove(player)
    if player not in entry["away"]:
        entry["away"].append(player)
        entry["away_since"][player] = now
    return method(self, state, player, _game_time(entry["started_at"], now))


def _record_join(self, method, outermost, state, player_id, now):
    # A game's initial_state can call on_join before PsyNet adds its entry.
    entry = state.get("psynet") if isinstance(state, dict) else None
    if entry is None or not outermost:
        return method(self, state, player_id, now)
    player = _player(entry, player_id)
    entry["last_event"] = now
    if player in entry["away"]:
        entry["away"].remove(player)
        entry["away_since"][player] = None
    return method(self, state, player, _game_time(entry["started_at"], now))


def _record_add(self, method, outermost, state, player_id, now):
    entry = _psynet_entry(state)
    if not outermost:
        return method(self, state, player_id, now)
    entry["participant_ids"].append(int(player_id))
    entry["last_event"] = now
    player = len(entry["participant_ids"]) - 1
    # Away until their page opens, so an away_timeout covers a player who
    # never arrives. A bot joins at once.
    entry["away"].append(player)
    entry["away_since"].append(now)
    # Once the game has started there is no ready step to wait for, so a
    # newcomer who never arrives is away rather than a no-show.
    if entry["started_at"] is not None:
        entry["ready"].append(player)
    return method(self, state, player, _game_time(entry["started_at"], now))


def _player_done(self, method, outermost, state, player_id):
    entry = _psynet_entry(state)
    if not outermost:
        return method(self, state, player_id)
    if entry["started_at"] is None:
        return False
    return method(self, state, _player(entry, player_id))


def _gone_at(self, entry, player):
    """Return when, on Dallinger's clock, an away player is gone: once away
    for the game's away_timeout, counted from the start for one who left
    before it."""
    return max(entry["away_since"][player], entry["started_at"]) + self.away_timeout


def _too_few_players_at(self, state):
    """Return when, on Dallinger's clock, too few players will be left
    for the game to go on, if the players away now stay away, or None.

    The game ends once fewer than its min_players aren't gone. Players whose
    game has ended don't count."""
    entry = _psynet_entry(state)
    if self.away_timeout is None or entry["started_at"] is None:
        return None
    done = self._players_done(state)
    gone_at = sorted(
        _gone_at(self, entry, player) for player in entry["away"] if player not in done
    )
    can_lose = len(entry["participant_ids"]) - len(done) - self.min_players
    if can_lose < 0:
        return entry["started_at"]
    return gone_at[can_lose] if len(gone_at) > can_lose else None


def _absences(self, state):
    """Return LiveGame.absences: each player's ``"no_show"``,
    ``"left_game"`` or None, as of the latest event the game handled, which
    for a game that has ended is its end."""
    entry = _psynet_entry(state)
    done = self._players_done(state)
    now = entry["last_event"]
    gone = (
        self.away_timeout is not None
        and entry["started_at"] is not None
        and now is not None
    )

    def absence(player):
        if player in done:
            return None
        if player not in entry["ready"]:
            return "no_show"
        if gone and player in entry["away"] and _gone_at(self, entry, player) <= now:
            return "left_game"
        return None

    return [absence(player) for player in range(len(entry["participant_ids"]))]


def _game_end(entry):
    """Return when the game ends at the latest, on the game's clock, or
    None."""
    ends_at = entry["ends_at"]
    return None if ends_at is None else ends_at - entry["started_at"]


def _add_psynet_entry(self, method, outermost, players, *settings):
    # Dallinger calls initial_state with the players alone, so a
    # PlayLiveGame's settings come from _new_session_settings.
    if not settings and _new_session_settings.get() is not None:
        settings = (_new_session_settings.get(),)
    participant_ids = [int(player_id) for player_id in players]
    state = method(self, list(range(len(participant_ids))), *settings)
    name = type(self).__name__
    if not isinstance(state, dict):
        raise TypeError(
            f"{name}.initial_state must return a dict, not {type(state).__name__}."
        )
    if "psynet" in state:
        raise ValueError(
            f"{name}.initial_state returned a state with a 'psynet' entry, "
            "which is PsyNet's. Give it another name."
        )
    state["psynet"] = {
        "participant_ids": participant_ids,
        "ready": [],
        "away": [],
        "away_since": [None] * len(participant_ids),
        "players_left": False,
        "duration": self.duration,
        "started_at": None,
        "ends_at": None,
        "time_up": False,
        "last_tick": None,
        "last_event": None,
    }
    return state


# Returned by an entry in _SESSION_BOOKKEEPING that left the state as it
# was, so it isn't converted.
_UNCHANGED = object()


# PsyNet's part of each state method, which keeps the psynet entry up
# to date and runs in the method's place, calling the game's own method.
_SESSION_BOOKKEEPING = {
    "apply": _apply_once_started,
    "tick": _tick_once_started,
    "on_leave": _record_leave,
    "on_join": _record_join,
    "on_add": _record_add,
    "is_done": _player_done,
    "initial_state": _add_psynet_entry,
}
