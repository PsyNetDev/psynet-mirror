from dallinger.realtime import RealtimeGame, create_realtime_session

from ..bot import Bot
from ..sync import GroupBarrier
from .game import LiveSession


class LiveSessionInitializer(GroupBarrier):
    """Starts a live session for each group that reaches this point in the
    timeline.

    Like a :class:`~psynet.sync.GroupBarrier`, it waits for every member of
    the participant's group to arrive. It then starts a session of
    ``game_type`` with the members as its players, and the group moves on
    together. A later page finds the session with :func:`live_session_id`. A
    group that arrives again, for example in a loop, plays a new session.

    Parameters
    ----------

    id_
        A name for this initializer, which pages pass to
        :func:`live_session_id` to find the group's session.

    group_type
        The ``group_type`` of the :class:`~psynet.sync.Grouper` whose groups
        play the game.

    game_type
        The game the group plays, a :class:`LiveSession` subclass with a
        ``bot`` method. Define it at the top level of a file, such as
        ``experiment.py``, not inside a function or another class.

    **kwargs
        Any other parameter of :class:`~psynet.sync.GroupBarrier`, such as
        ``max_wait_time``, except ``on_release``, which the initializer uses
        to start the session.
    """

    def __init__(self, id_: str, group_type: str, game_type, **kwargs):
        if not (isinstance(game_type, type) and issubclass(game_type, LiveSession)):
            raise TypeError(
                f"game_type must be a LiveSession subclass, not {game_type!r}."
            )
        if game_type.channel is None:
            raise TypeError(
                f"{game_type.__name__} has no channel, so it can't be played. "
                "Set its channel to a name for the game."
            )
        if game_type.bot is RealtimeGame.bot:
            raise TypeError(
                f"{game_type.__name__} has no bot method, so its bots, such as "
                "those of psynet test, would never move. Define bot to return "
                "a bot's next message."
            )
        super().__init__(
            id_=id_,
            group_type=group_type,
            on_release=LiveSessionInitializer._release,
            **kwargs,
        )
        self.game_type = game_type

    def receive_participant(self, participant):
        # So that a group that dissolves here leaves no earlier visit's session.
        _set_live_session_id(participant, self.id, None)
        super().receive_participant(participant)

    # on_release has to be importable by name, and gets the barrier rebuilt
    # from its saved settings.
    @staticmethod
    def _release(participants, barrier):
        barrier._start_session(participants)

    def _start_session(self, participants):
        session_id = create_realtime_session(
            self.game_type,
            [member.id for member in participants],
            bots=[member.id for member in participants if isinstance(member, Bot)],
        )
        for member in participants:
            _set_live_session_id(member, self.id, session_id)


def live_session_id(participant, initializer_id):
    """Return the id of the session that ``participant``'s group started at
    the :class:`LiveSessionInitializer` with the id ``initializer_id``.

    Returns ``None`` if the group hasn't started one there since the
    participant last arrived, for example because the group broke up while
    it waited.
    """
    return _live_session_ids(participant).get(initializer_id)


def _live_session_ids(participant):
    return participant.live_sessions or {}


def _set_live_session_id(participant, initializer_id, session_id):
    session_ids = {
        key: value
        for key, value in _live_session_ids(participant).items()
        if key != initializer_id
    }
    if session_id is not None:
        session_ids[initializer_id] = session_id
    participant.live_sessions = session_ids
