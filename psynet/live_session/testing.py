"""Helpers for testing a live session's game in Python, without a server."""

from .ready_step import _ready_step


def start_session(game, state, now=0):
    """Start the session in ``state``, as PsyNet does once every player is
    ready: it marks every player ready and runs the game's ``on_start``.
    Until the start, the game rejects messages and ``bot`` sends only the
    message that says the bot is ready, so a test of a message or of ``bot``
    starts the session first.

    ::

        from psynet.live_session.testing import start_session

        game = RockPaperScissors()
        state = game.initial_state(["1", "2"])
        start_session(game, state)

    Parameters
    ----------

    game
        The game, an instance of a :class:`~psynet.live_session.LiveSession`
        subclass.

    state
        A state that the game's ``initial_state`` returned.

    now
        The session time at which the session starts.
    """
    ready_step = _ready_step(state)
    ready_step["ready"] = list(ready_step["players"])
    game._start_session(state, now)
