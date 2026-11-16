"""Helpers for testing a game's rules in Python, without a server."""

from dallinger.realtime import Sent

from .messages import LiveMessage
from .psynet_entry import _psynet_entry


class LocalGame:
    """A game played in Python, for testing its rules without starting the
    experiment. It calls the game's methods as PsyNet does, so each player is
    known by their number, from 0, and times are seconds since the game
    started.

    ::

        from psynet.live_game.testing import LocalGame

        game = LocalGame(RockPaperScissors, players=2, settings={"rounds": 3})
        game.send(0, Choose(round=1, action="rock"))
        assert game.view(1)["partner_chosen"]

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
            If the game rejects the message.
        """
        if isinstance(message, LiveMessage):
            message = {
                "type": message.type,
                "message": message.model_dump(mode="json", by_alias=True),
            }
        self.game.apply(
            self.state, self._participant(player), message, self._clock(now), Sent()
        )

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
        """Return whether the game's ``is_over`` says the game is over, or
        the reason it gives, such as ``"players_left"``."""
        over = self.game.is_over(self.state)
        return over if isinstance(over, str) else bool(over)

    def outcome(self, reason="finished"):
        """Return the game's ``outcome``, as if it ended now for ``reason``."""
        return self.game.outcome(self.state, reason)

    def answer(self, player, reason="finished"):
        """Return ``player``'s answer, as if the game ended now for
        ``reason``."""
        return self.game.answer(self.outcome(reason), reason, player)

    def _participant(self, player):
        return str(_psynet_entry(self.state)["participant_ids"][player])

    def _clock(self, now):
        # Dallinger's clock, which the game's methods get converted from.
        started_at = _psynet_entry(self.state)["started_at"]
        return now + (started_at or 0)


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
    entry["ready"] = list(range(len(entry["participant_ids"])))
    game._end_ready_step(state, 0)
