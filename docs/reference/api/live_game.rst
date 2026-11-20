==========
Live games
==========

.. automodule:: psynet.live_game
    :members:
    :show-inheritance:
    :exclude-members: resolve, model_config, validate, get_participant_js_vars, check_ready_for_response

.. data:: NOT_STARTED
    :value: "The game hasn't started yet."

    The reason a message sent before the game starts is rejected.

.. data:: TIMEOUT
    :value: "timeout"

    The reason a game ends with when it reaches its
    :attr:`~psynet.live_game.LiveGame.timeout`.

.. data:: PLAYERS_LEFT
    :value: "players_left"

    The reason a game with an
    :attr:`~psynet.live_game.LiveGame.away_timeout` ends with when too few
    players are left.

.. data:: TOO_LATE
    :value: "too_late"

    The reason the game of a player added after the game's
    :meth:`~psynet.live_game.LiveGame.accepts_players` returned ``False``
    ends with, at once.

The reason a player's game ends with when the game's ``is_done`` returns
``True`` is what its :meth:`~psynet.live_game.LiveGame.done_reason` gives,
by default Dallinger's :data:`~dallinger.realtime.game.DONE`, ``"done"``,
and the game then rejects their messages with
:data:`~dallinger.realtime.game.PLAYER_DONE_REASON`.

Testing
-------

.. automodule:: psynet.live_game.testing
    :members:
