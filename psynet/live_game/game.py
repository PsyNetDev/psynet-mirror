"""LiveGame, the class a game extends: Dallinger's RealtimeGame with
PsyNet's typed messages, ready step, plain-data state and rewards.

``__init_subclass__`` wraps each game's own methods with the wrappers in
``method_wrappers.py``, so game code stays plain, and registers each game
that sets a ``channel``, so that the experiment adds it to
``realtime_games``.
"""

import functools

from dallinger.realtime import RealtimeGame, Reject
from dallinger.realtime.game import queued_effects
from dallinger.realtime.utils import is_number
from pydantic import PydanticInvalidForJsonSchema
from pydantic_core import to_jsonable_python

from .messages import (
    _STARTED_EFFECT,
    LiveMessage,
    _parse_message,
    _saved_messages,
    _session_channel,
)
from .method_wrappers import (
    _GAME_CODE_METHODS,
    _STATE_METHODS,
    _ends_when_time_is_up,
    _returns_json,
    _runs_game_code,
    _saves_ready_messages,
    _sends_message,
    _shows_psynet_entry,
    _stores_json,
    _waits_for_start,
)
from .psynet_entry import PlayerReady, _psynet_entry
from .registry import _register_live_game
from .reward import (
    _REWARD_EFFECT,
    _check_reward,
    _handles_ending,
    _handles_reward,
)


class LiveGame(RealtimeGame):
    """A game that a group of participants play together in real time.

    Set ``channel`` to a name for the game, list its message types in
    :attr:`messages`, and define ``initial_state``, ``view`` and ``bot``. The
    ``bot`` method plays for bots, as in ``psynet test``. A game can also
    define ``is_over``, ``outcome``, ``tick`` and the other methods of
    :class:`~dallinger.realtime.RealtimeGame`, which this class extends.
    Dallinger's `API reference
    <https://dallinger.readthedocs.io/latest/realtime_games.html#api-reference>`__
    describes each of them. A subclass of a game needs a ``channel`` of its
    own.

    The game's methods know each player by their number, from 0, in the
    order of the players' seats in the group (see
    :attr:`~psynet.sync.SyncGroup.seats`), and get
    ``now`` in seconds since the game started. The state and each view are
    dicts that hold only plain data, such as lists, strings and numbers, so
    a game keeps what each player has in a list, in player order.
    :doc:`/code/multiplayer/live_games` walks through a whole game, including
    how the game starts and which values PsyNet converts to plain data.
    """

    #: The game's message types, each a :class:`LiveMessage` subclass with
    #: its own :attr:`~LiveMessage.type`.
    messages = []

    #: Whether PsyNet converts the state to plain data after each method that
    #: changes it. A game with a very large state can set it to ``False`` to
    #: save the time the conversion takes. It then has to store only plain
    #: data itself.
    convert_state_to_json = True

    #: Seconds after the group's pages are sent to the game at which the
    #: game starts, even if some players aren't ready. They can still join
    #: and play.
    ready_timeout = 60

    #: Seconds the game lasts once it starts, or ``None``, the default, for a
    #: game that ends by itself, through ``is_over``.
    #:
    #: At the end, PsyNet runs the game's ``tick`` with the end as ``now``,
    #: even if the tick runs late. It then ends the game with the reason
    #: ``"finished"``, unless ``is_over`` has ended it already, and rejects
    #: any later messages. A page reads the time left from
    #: ``psynet.liveGame.secondsLeft()``, and the duration from
    #: ``psynet.liveGame.duration``.
    duration = None

    #: Seconds after it starts at which a game without a :attr:`duration`
    #: ends with the reason ``"timeout"``, if ``is_over`` hasn't ended it
    #: already, so that it ends even if a player walks away. Players can't
    #: leave the game page until the game ends, so set it to ``None``, for no
    #: limit, only if the game always ends by itself. Default: 600.
    timeout = 600

    #: The fewest players a game needs. A group that reaches the
    #: :class:`PlayLiveGame` with fewer active members, for example
    #: because the others left it while it waited, starts no game, and its
    #: members' game pages show the no-game notice. Set it to 1 for a game
    #: that a player can play alone.
    min_players = 2

    #: The most players a game can have, or ``None``, the default, for no
    #: limit. Set it when the game has something for each player that runs
    #: out, such as a color or a starting square. A group that reaches the
    #: :class:`PlayLiveGame` with more active members is a mistake in the
    #: experiment's design, so it starts no game, as for too few players,
    #: and PsyNet logs an error that says so.
    max_players = None

    #: Seconds a player can be away, with none of their game pages open,
    #: before they count as gone, or ``None``, the default, for a game that
    #: carries on however many players are away. Once fewer than
    #: :attr:`min_players` players aren't gone, the game ends with the
    #: reason ``"players_left"``. A player away when the game starts counts
    #: from the start. A reload or a dropped connection makes a player away
    #: for a moment, so allow for one, with 30 seconds or more.
    away_timeout = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Resolved through the MRO, so methods from a mixin are wrapped too.
        for name, wrap in [
            *(
                (name, functools.partial(_stores_json, name=name))
                for name in _STATE_METHODS
            ),
            ("initial_state", functools.partial(_returns_json, name="initial_state")),
            *((name, _runs_game_code) for name in _GAME_CODE_METHODS),
            ("next_deadline", _waits_for_start),
            ("is_over", _ends_when_time_is_up),
            ("view", _shows_psynet_entry),
            ("bot", _sends_message),
            ("save_message", _saves_ready_messages),
            ("handle_effect", _handles_reward),
            ("handle_ending", _handles_ending),
        ]:
            method = getattr(cls, name)
            if method is not getattr(RealtimeGame, name, None) and not getattr(
                method, "_psynet_wrapper", False
            ):
                setattr(cls, name, wrap(method))
        if not (isinstance(cls.min_players, int) and cls.min_players >= 1):
            raise ValueError(
                f"{cls.__name__}'s min_players must be a whole number of 1 or more."
            )
        if cls.max_players is not None and not (
            isinstance(cls.max_players, int)
            and not isinstance(cls.max_players, bool)
            and cls.max_players >= cls.min_players
        ):
            raise ValueError(
                f"{cls.__name__}'s max_players must be None or a whole number of "
                f"at least its min_players, {cls.min_players}."
            )
        if not is_number(cls.ready_timeout) or cls.ready_timeout <= 0:
            raise ValueError(
                f"{cls.__name__}'s ready_timeout must be a positive number."
            )
        if cls.away_timeout is not None and (
            not is_number(cls.away_timeout) or cls.away_timeout <= 0
        ):
            raise ValueError(
                f"{cls.__name__}'s away_timeout must be None or a positive number."
            )
        _set_max_duration(cls)
        cls._message_types = _index_message_types(cls)
        if cls.channel is not None:
            _register_live_game(cls)

    # Defined here, so the ready step runs in a game that doesn't define
    # them. Each calls on along the MRO, so a later base's method runs.
    @_stores_json
    def tick(self, state, now):
        """Advance ``state`` to ``now``, as in Dallinger's ``tick``. It runs
        only once the game has started.
        """
        return super().tick(state, now)

    @_stores_json
    def on_join(self, state, player, now):
        """Respond to a player arriving, as in Dallinger's ``on_join``. A
        player arrives when they open the game page while none of theirs is
        open, so it runs again after a reload or a dropped connection. A bot
        arrives as soon as its group reaches the game, before it starts. A
        player who comes back after leaving is no longer in
        ``state["psynet"]["away"]``. ``now`` is ``None`` before the game
        starts.
        """
        return super().on_join(state, player, now)

    @_stores_json
    def on_leave(self, state, player, now):
        """Respond to a player's last open page closing, as in Dallinger's
        ``on_leave``. By default the game carries on without them, or, with
        an :attr:`away_timeout`, until too few players are left. A player
        who leaves before the game starts isn't ready any more, and a player
        who leaves is in ``state["psynet"]["away"]`` until they come
        back. ``now`` is ``None`` before the game starts.
        """
        return super().on_leave(state, player, now)

    @_waits_for_start
    def next_deadline(self, state):
        """Return the time at which ``tick`` should next run, in seconds
        since the game started, as in Dallinger's ``next_deadline``. It's
        called only once the game has started.
        """
        return super().next_deadline(state)

    @_ends_when_time_is_up
    def is_over(self, state):
        """Return whether the game is over, as in Dallinger's ``is_over``.
        A game with a :attr:`duration` is also over once its time is up.
        """
        return super().is_over(state)

    @_stores_json
    def on_start(self, state):
        """Respond to the game starting, the moment the game's clock, ``now``
        in its other methods, starts at 0. ``state["psynet"]["ready"]``
        says which players were ready. A game can end here, through its
        ``is_over``.
        """

    @_stores_json
    def _end_ready_step(self, state, now):
        entry = _psynet_entry(state)
        if entry["started_at"] is None:
            entry["started_at"] = now
            limit = self.duration if self.duration is not None else self.timeout
            if limit is not None:
                entry["ends_at"] = now + limit
            if queued_effects.get(None) is not None:
                # Past this class's queue_effect, which refuses PsyNet's names.
                RealtimeGame.queue_effect(self, _STARTED_EFFECT, {})
            self.on_start(state)

    # Wrapped here, so __init_subclass__ doesn't copy a wrapper onto each
    # subclass, which would hide a later base's apply.
    @_stores_json
    def apply(self, state, player, message, now, sent):
        """Apply a page's message with its message type's
        :meth:`LiveMessage.apply`.

        Most games don't override this. A game that needs ``sent``, what the
        page reported about the message, such as when it sent it, can
        override it, read the message with :meth:`parse_message`, and apply it
        itself. An override runs only once the game has started, and never
        receives a :class:`PlayerReady` message, which PsyNet handles itself.
        """
        self.parse_message(message).apply(self, state, player, now)

    def save_message(self, state, player, message, rejection):
        """Return whether to save a page's message in the game's record,
        as in Dallinger's ``save_message``. By default, it asks the message's
        :meth:`LiveMessage.should_save`, and saves a message the game
        couldn't read. PsyNet always saves its own messages, such as
        :class:`PlayerReady`, without calling this.
        """
        try:
            parsed = self.parse_message(message)
        except Reject:
            return True
        return parsed.should_save(self, state, player, rejection)

    def answer(self, outcome, reason, player):
        """Return a player's answer on the game page, which is also their
        trial's answer when the game is played as a trial. By default, it's
        the whole outcome. Return only the player's part, such as
        ``outcome["payoffs"][player]``, so the trial doesn't hold the
        other players' data and code reading it doesn't need the player's
        number.
        It isn't called for a game that failed without an outcome, whose
        answer is ``None``.

        Parameters
        ----------

        outcome
            What the game's ``outcome`` returned.

        reason
            Why the game ended. It's the ``reason`` that the game's
            ``outcome`` received.

        player
            The player's number: 0 for the first player, 1 for the next,
            and so on.

        Returns
        -------

        A value that can be saved as JSON.
        """
        return outcome

    def performance_reward(self, outcome, reason, player):
        """Return the reward a player earns from the game's outcome, such as
        their winnings. PsyNet adds it to each player's performance reward
        once, when the game's result is saved, however the game ended,
        and also for a player who has left the game page. It isn't paid for a
        game that failed without an outcome, because its record couldn't be
        saved or its ``outcome`` raised an error. When the game is played in a
        trial, the reward is also added to that trial's
        ``performance_reward``. By default, there's no reward.

        Parameters
        ----------

        outcome
            What the game's ``outcome`` returned.

        reason
            Why the game ended. It's the ``reason`` that the game's
            ``outcome`` received.

        player
            The player's number: 0 for the first player, 1 for the next,
            and so on.

        Returns
        -------

        A number of 0 or more.
        """
        return 0

    def add_performance_reward(self, player, amount):
        """Add a reward earned during the game to a player's performance
        reward. Call it in a method that changes the state, such as a
        message's :meth:`~LiveMessage.apply`. PsyNet adds the reward a few
        seconds later, and the player keeps it even if they leave before the
        game ends. When the game is played in a trial, the reward is also
        added to that trial's ``performance_reward``. For a reward based on
        the outcome, define :meth:`performance_reward` instead.

        Parameters
        ----------

        player
            The player's number: 0 for the first player, 1 for the next,
            and so on.

        amount
            The reward, a number of 0 or more.
        """
        amount = _check_reward(amount, f"{type(self).__name__}.add_performance_reward")
        if isinstance(player, bool) or not isinstance(player, int) or player < 0:
            raise TypeError(
                f"{type(self).__name__}.add_performance_reward needs a player's "
                f"number, such as 0, not {player!r}."
            )
        if not amount:
            return
        # Past this class's queue_effect, which refuses PsyNet's own effect name.
        super().queue_effect(_REWARD_EFFECT, {"player": player, "amount": amount})

    # Wrapped here, so a game that queues no effects of its own doesn't need
    # to define it.
    @_handles_reward
    def handle_effect(self, name, payload, session_row):
        """Do the work of an effect the game queued with :meth:`queue_effect`,
        as in Dallinger's ``handle_effect``. PsyNet handles the rewards from
        :meth:`add_performance_reward` itself, so they never reach this method.
        """
        return super().handle_effect(name, payload, session_row)

    @_handles_ending
    def handle_ending(self, session_row):
        """Do work that needs the game's ending, as in Dallinger's
        ``handle_ending``. PsyNet pays each player's
        :meth:`performance_reward`, and copies the outcome to the round the
        game was played in, if any, as
        :attr:`~psynet.sync.SyncGroupRound.live_game_outcome`, before this
        method runs.
        """
        return super().handle_ending(session_row)

    def queue_effect(self, name, payload):
        """Queue an effect, as
        :meth:`~dallinger.realtime.RealtimeGame.queue_effect` does, with the
        payload converted to plain data in the same way as the state. A
        message's fields can go in the payload as they are.
        """
        if name in (_REWARD_EFFECT, _STARTED_EFFECT):
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

    def parse_message(self, message):
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

        ~psynet.live_game.Reject
            If the ``type`` isn't one of :attr:`messages`, or the fields don't
            match it.
        """
        return _parse_message(self._message_types, message)

    @classmethod
    def saved_messages(cls, game_id):
        """Return the messages saved for one play of this game, in the order
        the game applied them, as :class:`SavedMessage` objects.

        They include each player's :class:`PlayerReady` messages, and the
        messages the game rejected, such as those sent before the game
        starts. The record is written a few seconds behind the game, so for a
        game that's still being played, this returns the messages written
        so far.
        :doc:`/code/multiplayer/live_games` says when the record is
        complete.

        Parameters
        ----------

        game_id
            The game's id, as :func:`live_game_id` returns it.

        Raises
        ------

        KeyError
            If there is no game ``game_id``.

        ValueError
            If ``game_id`` is a game of another kind.
        """
        channel = _session_channel(game_id)
        if channel != cls.channel:
            raise ValueError(
                f"Game {game_id} is a game of {channel!r}, not {cls.channel!r}."
            )
        return _saved_messages(game_id, cls._message_types)


# Seconds that Dallinger's max_duration leaves after the latest moment the
# game can end, so the game ends on its own tick rather than at max_duration,
# which is only there in case it doesn't.
_MAX_DURATION_MARGIN = 30


def _set_max_duration(game_class):
    """Check a game's duration and time limit, and set Dallinger's
    max_duration from them."""
    name = game_class.__name__
    if "max_duration" in vars(game_class) and not vars(game_class).get(
        "_psynet_max_duration"
    ):
        raise TypeError(
            f"{name} sets max_duration, which PsyNet sets itself. Set its "
            "timeout instead, in seconds from when the game starts."
        )
    for what in ("duration", "timeout"):
        value = getattr(game_class, what)
        if value is not None and (not is_number(value) or value <= 0):
            raise ValueError(f"{name}'s {what} must be None or a positive number.")
    limit = (
        game_class.duration if game_class.duration is not None else game_class.timeout
    )
    game_class.max_duration = (
        None
        if limit is None
        else game_class.ready_timeout + limit + _MAX_DURATION_MARGIN
    )
    game_class._psynet_max_duration = True


def _index_message_types(game_class):
    by_type = {PlayerReady.type: PlayerReady}
    for message_type in game_class.messages:
        if not (
            isinstance(message_type, type) and issubclass(message_type, LiveMessage)
        ):
            raise TypeError(
                f"{game_class.__name__}.messages lists {message_type!r}, "
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
                f"{game_class.__name__}.messages lists {message_type.__name__}, "
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
