"""Live sessions: games that the members of a group play together in real
time, such as a negotiation or a game of moving and collecting things.

A game's rules are written as a game type, a subclass of Dallinger's
:class:`dallinger.realtime.RealtimeGame`. Dallinger plays the game on the
server, so every player's page sees the same game, and it saves each session
and its messages with the experiment's data. Dallinger's "Real-Time Games"
documentation explains how to write a game type.

To have groups play a game, put a :class:`LiveSessionInitializer` in the
timeline after the :class:`~psynet.sync.Grouper` that forms the groups. When
a group's members have all reached it, it starts a session of the game, and
the group moves on together. A page after it finds the session with
:func:`live_session_id`.

Dallinger plays only the game types listed in the experiment's
``realtime_games``. PsyNet adds every initializer's game type to that list,
so the experiment doesn't need to list them.

::

    timeline = Timeline(
        SimpleGrouper(group_type="pair", initial_group_size=2),
        LiveSessionInitializer(
            id_="bargaining",
            group_type="pair",
            game_type=Bargaining,  # a RealtimeGame subclass
        ),
        ...
    )
"""

from dallinger.realtime import create_realtime_session

from .sync import GroupBarrier


class LiveSessionInitializer(GroupBarrier):
    """Starts a session of a game for each group that reaches it.

    Like a :class:`~psynet.sync.GroupBarrier`, it waits until every member of
    the participant's group has arrived. It then starts a session of
    ``game_type`` with the members as its players, and the group moves on.
    A page later in the timeline finds the session with
    :func:`live_session_id`. A group that reaches the initializer again, for
    example in a loop, plays a new session.

    Put the initializer in the experiment's ``timeline``, not in a page or
    trial built while the experiment runs, such as one returned by a trial's
    ``show_trial``: PsyNet finds the game types it needs in the timeline.

    Parameters
    ----------

    id_
        A name for the initializer. Pages pass it to :func:`live_session_id`
        to find the group's session.

    group_type
        The ``group_type`` of the :class:`~psynet.sync.Grouper` whose groups
        play the game.

    game_type
        The game the group plays, a subclass of
        :class:`dallinger.realtime.RealtimeGame`. Define it at the top level
        of a module, such as ``experiment.py``, not inside a function or
        another class.

    **kwargs
        Any other parameter of :class:`~psynet.sync.GroupBarrier`, such as
        ``max_wait_time``, except ``on_release``, which the initializer uses
        to start the session.
    """

    def __init__(self, id_: str, group_type: str, game_type, **kwargs):
        super().__init__(
            id_=id_, group_type=group_type, on_release=_start_live_session, **kwargs
        )
        self.game_type = game_type

    def receive_participant(self, participant):
        # So that a group that dissolves here leaves no earlier visit's session.
        if participant.live_sessions:
            participant.live_sessions.pop(self.id, None)
        super().receive_participant(participant)


def _start_live_session(participants, barrier):
    session_id = create_realtime_session(
        barrier.game_type, [member.id for member in participants]
    )
    for member in participants:
        member.live_sessions = {**(member.live_sessions or {}), barrier.id: session_id}


def live_session_id(participant, initializer_id):
    """Return the id of the session that ``participant``'s group started at
    the :class:`LiveSessionInitializer` named ``initializer_id``.

    Returns ``None`` if the group hasn't started one there since the
    participant last arrived, for example because the group broke up while it
    waited.
    """
    return (participant.live_sessions or {}).get(initializer_id)


def _timeline_game_types(timeline):
    return [
        elt.links["barrier"].game_type
        for elt in timeline.all_elts
        if isinstance(elt.links.get("barrier"), LiveSessionInitializer)
    ]
