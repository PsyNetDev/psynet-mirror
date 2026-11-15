"""Helpers for testing a live session's game in Python, without a server."""

from .session_entry import _live_session_entry


def start_session(game, state, now=0):
    """Start the game in ``state``, as PsyNet does once every player is
    ready: it marks every player ready and runs the game's ``on_start``.
    Until the game starts, the game rejects messages and ``bot`` sends only the
    message that says the bot is ready, so a test of a message or of ``bot``
    starts the game first.

    ::

        from psynet.live_session.testing import start_session

        game = RockPaperScissors()
        state = game.initial_state(["1", "2"])
        start_session(game, state)

    Parameters
    ----------

    game
        The game, an instance of a :class:`~psynet.live_session.LiveGame`
        subclass.

    state
        A state that the game's ``initial_state`` returned.

    now
        The session time at which the game starts.
    """
    entry = _live_session_entry(state)
    entry["ready"] = list(entry["players"])
    game._end_ready_step(state, now)
