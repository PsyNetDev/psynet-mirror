"""Helpers for testing a game's rules in Python, without a server."""

import json
import math
import time
from dataclasses import dataclass

from dallinger.realtime import Reject, Sent
from dallinger.realtime.game import PLAYER_DONE_REASON, queued_effects

from .messages import LiveMessage
from .psynet_entry import _psynet_entry


class LocalGame:
    """A game played in Python, for testing its rules without starting the
    experiment. It calls the game's methods as PsyNet does, so each player is
    known by their number, from 0, and times are seconds since the game
    started.

    ::

        from psynet.live_game.testing import LocalGame

        game = LocalGame(
            RockPaperScissors, players=2, settings={"throws": 3, "reward_per_win": 0.10}
        )
        game.send(0, Choose(throw=1, action="rock"))
        assert game.view(1)["partner_chosen"]

    The rewards that the game adds with
    :meth:`~psynet.live_game.LiveGame.add_performance_reward`, the moments it
    records and the effects it queues are dropped.

    Parameters
    ----------

    game_class
        The game, a :class:`~psynet.live_game.LiveGame` subclass.

    players
        How many players the game has.

    settings
        The settings, as a :class:`~psynet.live_game.PlayLiveGame` would give
        them, for a game whose ``initial_state`` takes them.

    start
        Whether to start the game at once, as PsyNet does once every player
        is ready. Until it starts, the game rejects messages.
    """

    def __init__(self, game_class, players, settings=None, start=True):
        #: The game, an instance of ``game_class``.
        self.game = game_class()
        # As a runner does, so that the game's methods can queue effects.
        queued_effects.set([])
        participants = [str(number + 1) for number in range(players)]
        if settings is None:
            #: The game's state.
            self.state = self.game.initial_state(participants)
        else:
            self.state = self.game.initial_state(participants, settings)
        if start:
            self.start()

    def start(self):
        """Start the game, marking every player ready."""
        start_game(self.game, self.state)

    def send(self, player, message, now=0):
        """Apply a message from ``player``, ``now`` seconds into the game.

        ``message`` is a :class:`~psynet.live_game.LiveMessage`, or what a page
        sends, such as ``{"type": "choose", "message": {"action": "rock"}}``.

        Raises
        ------

        ~psynet.live_game.Reject
            If the game rejects the message, or the player's game has ended,
            by the game's ``is_done``. As in a live game, the state is then
            as it was before the message.
        """
        if self.is_done(player):
            raise Reject(PLAYER_DONE_REASON)
        if isinstance(message, LiveMessage):
            message = {
                "type": message.type,
                "message": message.model_dump(mode="json", by_alias=True),
            }
        before = json.dumps(self.state)
        try:
            self.game.apply(
                self.state, self._participant(player), message, self._clock(now), Sent()
            )
        except Reject:
            # In place, so a caller holding game.state still sees the game.
            self.state.clear()
            self.state.update(json.loads(before))
            raise

    def tick(self, now):
        """Run the game's ``tick``, ``now`` seconds into the game."""
        self.game.tick(self.state, self._clock(now))

    def leave(self, player, now=0):
        """Close ``player``'s last game page, ``now`` seconds into the game,
        which runs the game's ``on_leave``."""
        self.game.on_leave(self.state, self._participant(player), self._clock(now))

    def join(self, player, now=0):
        """Open a game page for ``player``, ``now`` seconds into the game,
        which runs the game's ``on_join``."""
        self.game.on_join(self.state, self._participant(player), self._clock(now))

    def add(self, now=0):
        """Add a player to the game, ``now`` seconds into the game, which
        runs the game's ``on_add``, and open a game page for them, which
        runs its ``on_join``. Return the new player's number."""
        participant = str(max(_psynet_entry(self.state)["participant_ids"]) + 1)
        self.game.on_add(self.state, participant, self._clock(now))
        self.game.on_join(self.state, participant, self._clock(now))
        return len(_psynet_entry(self.state)["participant_ids"]) - 1

    def is_done(self, player):
        """Return whether ``player``'s game has ended, by the game's
        ``is_done``."""
        return bool(self.game.is_done(self.state, self._participant(player)))

    def done_reason(self, player):
        """Return why ``player``'s game ended, as the game's ``done_reason``
        gives it. Call it once :meth:`is_done` returns ``True``."""
        return _check_reason(
            self.game, "done_reason", self.state, self._participant(player)
        )

    def view(self, player):
        """Return what ``player``'s page shows, as the game's ``view`` returns
        it, with PsyNet's entry."""
        return self.game.view(self.state, self._participant(player))

    def bot(self, player, now=0):
        """Return the message a bot playing as ``player`` sends next, as a
        page would send it, or ``None``."""
        return self.game.bot(
            self.view(player), self._participant(player), self._clock(now)
        )

    def is_over(self):
        """Return whether the game's ``is_over`` says the game is over."""
        return bool(self.game.is_over(self.state))

    def end_reason(self):
        """Return why the game ended, as the game's ``end_reason`` gives it,
        such as ``"players_left"``. Call it once :meth:`is_over` returns
        ``True``."""
        return _check_reason(self.game, "end_reason", self.state)

    def outcome(self, reason="finished"):
        """Return the game's ``outcome``, as if it ended now for ``reason``."""
        return self.game.outcome(self.state, reason)

    def answer(self, player, reason="finished"):
        """Return ``player``'s answer, as if the game ended now for
        ``reason``."""
        return self.game.answer(self.outcome(reason), reason, player)

    def time_play(self, seconds=60):
        """Play the game with its bots for ``seconds`` of game time, timing its
        code, to estimate how many games a game runner can play at once.

        Each turn runs as a runner's would: a ``tick`` if one is due, then
        each player's bot moves, then each player's ``view``, with the state
        and the views encoded as JSON, as the runner saves and sends them. A
        game with a ``tick_rate`` has a turn per tick. One without has a turn
        at each of its deadlines and a turn a second, as if each player acted
        about once a second. Play stops early if the game ends, and the
        ``LocalGame`` is left where play stopped, so time a new one each
        time.

        ::

            print(LocalGame(Snake, players=4).time_play(30))

        Returns
        -------

        TimedPlay
        """
        players = range(len(_psynet_entry(self.state)["participant_ids"]))
        turns, code_seconds, slowest = 0, 0.0, 0.0
        now = 0.0
        # As in Dallinger's runner, a deadline ticks once: a later one must
        # come after it.
        last_deadline = -math.inf
        while not self.is_over():
            due, deadline = self._next_turn(now, last_deadline)
            if due > seconds:
                break
            now = due
            began = time.perf_counter()
            if self.game.tick_rate or deadline is not None:
                self.tick(now)
                if deadline is not None:
                    last_deadline = deadline
            # As in Dallinger, bots don't play after a tick ends the game.
            for player in players:
                if self.is_over():
                    break
                if self.is_done(player):
                    continue
                message = self.bot(player, now)
                if message is not None:
                    try:
                        self.send(player, message, now)
                    except Reject:
                        pass
            json.dumps([self.view(player) for player in players])
            json.dumps(self.state)
            took = time.perf_counter() - began
            turns += 1
            code_seconds += took
            slowest = max(slowest, took)
        return TimedPlay(type(self.game).__name__, now, turns, code_seconds, slowest)

    def _next_turn(self, now, last_deadline):
        """Return when :meth:`time_play`'s next turn after ``now`` is due, and
        the game deadline it ticks for, or ``None``.

        A game with a ``tick_rate`` has a turn per tick. One without has a
        turn on the next whole second, or at its next deadline after
        ``last_deadline`` if that comes first.
        """
        step = 1 / self.game.tick_rate if self.game.tick_rate else 1
        due = (math.floor(now / step + 1e-9) + 1) * step
        if self.game.tick_rate:
            return due, None
        deadline = self.game.next_deadline(self.state)
        if deadline is None:
            return due, None
        deadline -= _psynet_entry(self.state)["started_at"] or 0
        if deadline <= last_deadline or deadline > due:
            return due, None
        return max(deadline, now), deadline

    def _participant(self, player):
        return str(_psynet_entry(self.state)["participant_ids"][player])

    def _clock(self, now):
        # Dallinger's clock, which the game's methods get converted from.
        started_at = _psynet_entry(self.state)["started_at"]
        return now + (started_at or 0)


def _check_reason(game, name, *args):
    """Return what the game's method ``name`` returns, which, as in a live
    game, must be a non-empty string."""
    reason = getattr(game, name)(*args)
    if not isinstance(reason, str) or not reason:
        raise TypeError(
            f"{type(game).__name__}.{name} returned {reason!r}, not a non-empty string."
        )
    return reason


def start_game(game, state):
    """Start the game in ``state``, as PsyNet does once every player is
    ready: it marks every player ready and runs the game's ``on_start``.
    :class:`LocalGame` does this for you.

    Parameters
    ----------

    game
        The game, an instance of a :class:`~psynet.live_game.LiveGame`
        subclass.

    state
        A state that the game's ``initial_state`` returned.
    """
    entry = _psynet_entry(state)
    entry["ready"] = [
        player
        for player in range(len(entry["participant_ids"]))
        if player not in entry["too_late"]
    ]
    game._end_ready_step(state, 0)
    # As after the apply or tick that starts a live game.
    game._close_unless_accepting(state)


# A game runner is sized to be this busy, as async workers are, leaving room
# for bursts and for saving games and sending views, which time_play leaves out.
_TARGET_RUNNER_SHARE = 0.7


@dataclass
class TimedPlay:
    """How long a game's code took to play, from :meth:`LocalGame.time_play`."""

    #: The game's class name.
    game: str
    #: The game time played, in seconds.
    seconds: float
    #: The turns played.
    turns: int
    #: The seconds the game's code took over all the turns.
    code_seconds: float
    #: The seconds the slowest turn took.
    slowest_turn: float

    @property
    def runner_share(self):
        """Return the share of a game runner's time that one game needs."""
        return self.code_seconds / self.seconds if self.seconds else 0.0

    @property
    def games_per_runner(self):
        """Return about how many games one game runner can play at once,
        leaving it room for bursts and for saving games and sending views."""
        if not self.runner_share:
            return None
        return int(_TARGET_RUNNER_SHARE / self.runner_share)

    def __str__(self):
        per_turn = self.code_seconds / self.turns * 1000 if self.turns else 0
        text = (
            f"{self.game}: {self.turns:,} turns in {self.seconds:g} s of play "
            f"took {self.code_seconds:.3f} s of game code ({per_turn:.2f} ms a "
            f"turn on average, {self.slowest_turn * 1000:.2f} ms at most), "
            f"{_percent(self.runner_share)} of a game runner"
        )
        if self.runner_share > 1:
            text += ", more than a runner has, so make it faster"
        elif self.games_per_runner == 0:
            text += (
                ", so a runner can play only this game, with too little room "
                "for bursts, saving and sending views"
            )
        elif self.games_per_runner is not None:
            text += f", so one runner can play about {self.games_per_runner:,} games at once"
        return text + "."


def _percent(share):
    """Format ``share`` as a percentage with two significant figures, so that
    small shares still differ, such as 0.059% and 0.12%."""
    percent = share * 100
    return f"{percent:.0f}%" if percent >= 10 else f"{percent:.2g}%"
