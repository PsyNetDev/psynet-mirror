"""LiveGame, the class a game extends: Dallinger's RealtimeGame with
PsyNet's typed messages, ready step, plain-data state and rewards.

``__init_subclass__`` wraps each game's own methods with the wrappers in
``method_wrappers.py``, so game code stays plain, and registers each game
that sets a ``channel``, so that the experiment adds it to
``realtime_games``.
"""

import functools

from dallinger.realtime import RealtimeGame
from dallinger.realtime.utils import is_number
from pydantic import PydanticInvalidForJsonSchema
from pydantic_core import to_jsonable_python

from .messages import LiveMessage, _parse_message, _saved_messages, _session_channel
from .method_wrappers import (
    _STATE_METHODS,
    _returns_json,
    _sends_message,
    _shows_ready_step,
    _stores_json,
    _waits_for_start,
)
from .ready_step import PlayerReady, _ready_step
from .registry import _register_live_session
from .reward import _REWARD_EFFECT, _check_reward, _handles_reward


class LiveGame(RealtimeGame):
    """A game that a group plays in a live session.

    Set ``channel`` to a name for the game, list its message types in
    :attr:`messages`, and define ``initial_state``, ``view`` and ``bot``. The
    ``bot`` method plays for bots, as in ``psynet test``. A game can also
    define ``is_over``, ``outcome``, ``tick`` and the other methods of
    :class:`~dallinger.realtime.RealtimeGame`, which this class extends.
    Dallinger's `API reference
    <https://dallinger.readthedocs.io/latest/realtime_games.html#api-reference>`__
    describes each of them. A subclass of a game needs a ``channel`` of its
    own.

    The state and each view are dicts that hold only plain data, such as
    lists, strings and numbers. :doc:`/code/multiplayer/live_sessions` walks
    through a whole game, including how the session starts and which values
    PsyNet converts to plain data.
    """

    #: The game's message types, each a :class:`LiveMessage` subclass with
    #: its own :attr:`~LiveMessage.type`.
    messages = []

    #: Whether PsyNet converts the state to plain data after each method that
    #: changes it. A game with a very large state can set it to ``False`` to
    #: save the time the conversion takes. It then has to store only plain
    #: data itself.
    convert_state_to_json = True

    #: Seconds on the session clock after which the session starts, even if
    #: some players aren't ready. They can still join and play. ``None``
    #: waits for every player, until ``max_duration`` at the latest.
    ready_timeout = 60

    #: Seconds on the session clock after which the session ends with the
    #: reason ``"max_duration"``, if the game hasn't ended it already. Players
    #: can't leave the game page until the session ends, so set it to
    #: ``None``, for no limit, only if the game always ends by itself.
    max_duration = 600

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Resolved through the MRO, so methods from a mixin are wrapped too.
        for name, wrap in [
            *(
                (name, functools.partial(_stores_json, name=name))
                for name in _STATE_METHODS
            ),
            ("initial_state", functools.partial(_returns_json, name="initial_state")),
            ("next_deadline", _waits_for_start),
            ("view", _shows_ready_step),
            ("bot", _sends_message),
            ("handle_effect", _handles_reward),
        ]:
            method = getattr(cls, name)
            if method is not getattr(RealtimeGame, name, None) and not getattr(
                method, "_psynet_wrapper", False
            ):
                setattr(cls, name, wrap(method))
        if cls.ready_timeout is not None and (
            not is_number(cls.ready_timeout) or cls.ready_timeout <= 0
        ):
            raise ValueError(
                f"{cls.__name__}'s ready_timeout must be None or a positive number."
            )
        cls._message_types = _index_message_types(cls)
        if cls.channel is not None:
            _register_live_session(cls)

    # Defined here, so the ready step runs in a game that doesn't define
    # them. Each calls on along the MRO, so a later base's method runs.
    @_stores_json
    def tick(self, state, now):
        """Advance ``state`` to ``now``, as in Dallinger's ``tick``. It runs
        only once the session has started.
        """
        return super().tick(state, now)

    @_stores_json
    def on_join(self, state, player_id, now):
        """Respond to a player arriving, as in Dallinger's ``on_join``. A
        player arrives when they open the game page while none of theirs is
        open, so it runs again after a reload or a dropped connection. A bot
        arrives when the session starts. A player who comes back after
        leaving is no longer in ``state["live_session"]["away"]``.
        """
        return super().on_join(state, player_id, now)

    @_stores_json
    def on_leave(self, state, player_id, now):
        """Respond to a player's last open page closing, as in Dallinger's
        ``on_leave``. By default the game carries on without them. A player
        who leaves before the start isn't ready any more, and a player who
        leaves is in ``state["live_session"]["away"]`` until they come back.
        """
        return super().on_leave(state, player_id, now)

    @_waits_for_start
    def next_deadline(self, state):
        """Return the session time at which ``tick`` should next run, as in
        Dallinger's ``next_deadline``. Until the session starts, PsyNet waits
        for :attr:`ready_timeout` instead.
        """
        return super().next_deadline(state)

    @_stores_json
    def on_start(self, state, now):
        """Respond to the session starting, such as by setting the game's
        deadlines from ``now``. ``state["live_session"]["ready"]`` says which
        players were ready. A game can end the session here, through its
        ``is_over``.
        """

    @_stores_json
    def _start_session(self, state, now):
        ready_step = _ready_step(state)
        if ready_step["started_at"] is None:
            ready_step["started_at"] = now
            self.on_start(state, now)

    # Wrapped here, so __init_subclass__ doesn't copy a wrapper onto each
    # subclass, which would hide a later base's apply.
    @_stores_json
    def apply(self, state, player_id, message, now, sent):
        """Apply a page's message with its message type's
        :meth:`LiveMessage.apply`.

        Most games don't override this. A game that needs ``sent``, what the
        page reported about the message, such as when it sent it, can
        override it, read the message with :meth:`read_message`, and apply it
        itself. An override runs only once the session has started, and never
        receives a :class:`PlayerReady` message, which PsyNet handles itself.
        """
        self.read_message(message).apply(self, state, player_id, now)

    def performance_reward(self, outcome, reason, player_id):
        """Return the reward a player earns from the session's outcome, such as
        their winnings. PsyNet adds it to the player's performance reward when
        they leave the game page, once per session. It isn't paid for a
        session that failed without an outcome, because its record couldn't be
        saved or its ``outcome`` raised an error. By default, there's no reward.

        Parameters
        ----------

        outcome
            What the game's ``outcome`` returned.

        reason
            Why the session ended. It's the ``reason`` that the game's
            ``outcome`` received.

        player_id
            The player's id.

        Returns
        -------

        A number of 0 or more.
        """
        return 0

    def add_performance_reward(self, player_id, amount):
        """Add a reward earned during the game to a player's performance
        reward. Call it in a method that changes the state, such as a
        message's :meth:`~LiveMessage.apply`. PsyNet adds the reward a few
        seconds later, and the player keeps it even if they leave before the
        game ends. For a reward based on the outcome, define :meth:`performance_reward`
        instead.

        Parameters
        ----------

        player_id
            The player's id.

        amount
            The reward, a number of 0 or more.
        """
        amount = _check_reward(amount, f"{type(self).__name__}.add_performance_reward")
        if not amount:
            return
        super().queue_effect(
            _REWARD_EFFECT, {"player_id": str(player_id), "amount": amount}
        )

    # Wrapped here, so a game that queues no effects of its own doesn't need
    # to define it.
    @_handles_reward
    def handle_effect(self, name, payload, session_row):
        """Do the work of an effect the game queued with :meth:`queue_effect`,
        as in Dallinger's ``handle_effect``. PsyNet handles the rewards from
        :meth:`add_performance_reward` itself, so they never reach this method.
        """
        return super().handle_effect(name, payload, session_row)

    def queue_effect(self, name, payload):
        """Queue an effect, as
        :meth:`~dallinger.realtime.RealtimeGame.queue_effect` does, with the
        payload converted to plain data in the same way as the state. A
        message's fields can go in the payload as they are.
        """
        if name == _REWARD_EFFECT:
            raise ValueError(
                f"The effect name {name!r} is reserved for PsyNet's "
                "add_performance_reward. Give the effect another name."
            )
        try:
            payload = to_jsonable_python(payload)
        except (ValueError, TypeError) as error:
            raise ValueError(
                f"The {name!r} effect's payload holds a value PsyNet can't "
                f"convert to JSON. {error}."
            ) from None
        super().queue_effect(name, payload)

    def read_message(self, message):
        """Check a page's message and return it as a :class:`LiveMessage`.

        Avoid overriding this method. :meth:`saved_messages` doesn't call
        it, so a message that only your own reading accepts, such as an older
        shape of a message, comes back from :meth:`saved_messages` with its
        ``message`` set to ``None``.

        Parameters
        ----------

        message
            What the page sent, such as
            ``{"type": "choose", "message": {"action": "rock"}}``.

        Raises
        ------

        ~dallinger.realtime.Reject
            If the ``type`` isn't one of :attr:`messages`, or the fields don't
            match it.
        """
        return _parse_message(self._message_types, message)

    @classmethod
    def saved_messages(cls, session_id):
        """Return the messages saved for a session of this game, in the order
        the game applied them, as :class:`SavedMessage` objects.

        They include each player's :class:`PlayerReady` messages, and the messages
        the game rejected, such as those sent before the start. The record is
        written a few seconds behind the game, so for a session that's still
        being played, this returns the messages written so far.
        :doc:`/code/multiplayer/live_sessions` says when the record is
        complete.

        Parameters
        ----------

        session_id
            The session's id, as :func:`live_session_id` returns it.

        Raises
        ------

        KeyError
            If there is no session ``session_id``.

        ValueError
            If the session is of another game.
        """
        channel = _session_channel(session_id)
        if channel != cls.channel:
            raise ValueError(
                f"Session {session_id} is a session of {channel!r}, "
                f"not {cls.channel!r}."
            )
        return _saved_messages(session_id, cls._message_types)


def _index_message_types(game_type):
    by_type = {PlayerReady.type: PlayerReady}
    for message_type in game_type.messages:
        if not (
            isinstance(message_type, type) and issubclass(message_type, LiveMessage)
        ):
            raise TypeError(
                f"{game_type.__name__}.messages lists {message_type!r}, "
                "which isn't a LiveMessage subclass."
            )
        if "type" in message_type.model_fields:
            raise TypeError(
                f"{message_type.__name__}.type has an annotation, which makes it "
                'a field. Set it without one, as in type = "choose".'
            )
        name = message_type.type
        if not isinstance(name, str) or not name:
            raise TypeError(f"{message_type.__name__}.type must be a non-empty string.")
        if message_type.apply is LiveMessage.apply:
            raise TypeError(f"{message_type.__name__} must define apply.")
        try:
            message_type.model_json_schema()
        except PydanticInvalidForJsonSchema as error:
            raise TypeError(
                f"{message_type.__name__} has a field of a type Pydantic can't "
                f"read from JSON. {str(error).splitlines()[0]}"
            ) from None
        if name == PlayerReady.type:
            raise ValueError(
                f"{game_type.__name__}.messages lists {message_type.__name__}, "
                f"with the type {name!r}, which is PsyNet's PlayerReady message. "
                "Every game reads PlayerReady, so don't list it, and give other "
                "messages another type."
            )
        if name in by_type:
            raise ValueError(
                f"{by_type[name].__name__} and {message_type.__name__} "
                f"both have the type {name!r}."
            )
        by_type[name] = message_type
    return by_type
