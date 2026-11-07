"""Helpers for testing a live session's game in Python, without a server."""


def start_session(game, state, now=0):
    """Start the session in ``state``, as PsyNet does once every player is
    ready. Until then the game rejects messages and ``bot`` sends nothing, so
    a test of a message or of ``bot`` starts the session first. It runs the
    game's ``on_start``.

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
    game._start_session(state, now)
