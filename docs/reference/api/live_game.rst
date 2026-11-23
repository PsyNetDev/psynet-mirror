==========
Live games
==========

.. automodule:: psynet.live_game
    :members:
    :show-inheritance:
    :exclude-members: resolve, model_config, validate, get_participant_js_vars, check_ready_for_response

.. data:: NOT_STARTED_MESSAGE
    :value: "The game hasn't started yet."

    The reason a message sent before the game starts is rejected.

.. data:: FINISHED
    :value: "finished"

    The reason a game ends with when its
    :meth:`~psynet.live_game.LiveGame.is_over` returns ``True``, unless its
    :meth:`~psynet.live_game.LiveGame.end_reason` gives one of its own, or
    when it reaches its :attr:`~psynet.live_game.LiveGame.duration`. It's
    Dallinger's :data:`~dallinger.realtime.game.FINISHED`.

.. data:: FAILED
    :value: "failed"

    The reason a game ends with when its code raises an error; its record's
    :attr:`~psynet.live_game.LiveGameRecord.status` is then
    :attr:`~psynet.live_game.LiveGameStatus.FAILED`. It's Dallinger's
    :data:`~dallinger.realtime.game.FAILED`.

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
    ends with, at once. A participant who joined as the game ended, before
    Dallinger could add them, has it as their record's
    :attr:`~psynet.live_game.LiveGameRecord.done_reason` too.

The reason a player's game ends with when the game's ``is_done`` returns
``True`` is what its :meth:`~psynet.live_game.LiveGame.done_reason` gives,
by default Dallinger's :data:`~dallinger.realtime.game.DONE`, ``"done"``,
and the game then rejects their messages with
:data:`~dallinger.realtime.game.PLAYER_DONE_REASON`.

Testing
-------

.. automodule:: psynet.live_game.testing
    :members:
