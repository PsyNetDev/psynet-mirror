"""LiveGameBarrier, the group barrier that starts a session, and
live_session_id, which finds it.

When the barrier releases a group, it starts a Dallinger real-time session
and stores its id in each member's ``live_sessions``, keyed by the
game barrier's id. Reaching the game barrier sets that entry to ``None`` first,
so a page finds only the session from the participant's latest visit, and an
id without an entry is one whose game barrier the participant never reached.
"""

import inspect
import json

from dallinger.realtime import RealtimeGame, create_realtime_session

from ..barrier_spec import BarrierSpecError, barrier_spec_json
from ..bot import Bot
from ..sync import BarrierBehaviorMismatch, GroupBarrier
from ..timeline import CodeBlock, join
from .game import LiveGame
from .ready_step import _new_session_settings


class LiveGameBarrier(GroupBarrier):
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
        A name for this game barrier, which pages pass to
        :func:`live_session_id` to find the group's session.

    group_type
        The ``group_type`` of the :class:`~psynet.sync.Grouper` whose groups
        play the game.

    game_type
        The game the group plays, a :class:`LiveGame` subclass with a
        ``bot`` method. Define it at the top level of a file, such as
        ``experiment.py``, not inside a function or another class.

    settings
        Settings for the sessions this game barrier starts, such as the
        number of rounds: a dict, or any other value that can be saved as
        JSON. The game's ``initial_state`` gets it as a second argument, so
        define that as ``initial_state(self, players, settings)``. In a
        trial's ``show_trial``, pass the trial's ``definition`` to play each
        trial's game with that trial's settings. The members of a group must
        all arrive with the same settings, so give the trial class, or its
        trial maker, the group's ``sync_group_type``, which gives them the
        same trial.

    **kwargs
        Any other parameter of :class:`~psynet.sync.GroupBarrier`, such as
        ``max_wait_time``, except ``on_release``, which the game barrier uses
        to start the session.
    """

    def __init__(self, id_: str, group_type: str, game_type, settings=None, **kwargs):
        if not (isinstance(game_type, type) and issubclass(game_type, LiveGame)):
            raise TypeError(
                f"game_type must be a LiveGame subclass, not {game_type!r}."
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
        settings = _checked_settings(game_type, settings)
        super().__init__(
            id_=id_,
            group_type=group_type,
            on_release=LiveGameBarrier._release,
            **kwargs,
        )
        self.game_type = game_type
        self.settings = settings
        try:
            barrier_spec_json(self)
        except BarrierSpecError as error:
            raise TypeError(
                f"The LiveGameBarrier {id_!r} can't be saved: {error}"
            ) from None

    def receive_participant(self, participant):
        try:
            return super().receive_participant(participant)
        except BarrierBehaviorMismatch:
            raise ValueError(
                f"Participant {participant.id} arrived at the "
                f"LiveGameBarrier {self.id!r} with settings that differ "
                "from those of the members of their group who are waiting "
                "there. The members of a group must all arrive with the same "
                "settings, so if they come from a trial's definition, give "
                "the trial class, or its trial maker, the group's sync_group_type."
            ) from None

    def resolve(self):
        # Ahead of the barrier, which a participant who has left the group
        # passes without arriving at it.
        return join(CodeBlock(self._forget_session), super().resolve())

    def _forget_session(self, participant):
        _set_live_session_id(participant, self.id, None)

    # on_release has to be importable by name, and gets the barrier rebuilt
    # from its saved settings.
    @staticmethod
    def _release(participants, barrier, group_round):
        barrier._start_session(participants, group_round)

    def _start_session(self, participants, group_round=None):
        token = _new_session_settings.set(self.settings)
        try:
            session_id = create_realtime_session(
                self.game_type,
                [member.id for member in participants],
                bots=[member.id for member in participants if isinstance(member, Bot)],
            )
        finally:
            _new_session_settings.reset(token)
        for member in participants:
            _set_live_session_id(member, self.id, session_id)
        if group_round is not None:
            group_round.live_session_id = session_id


# Checked when the timeline is built, since an error while a group is
# released is only logged, and leaves the group waiting.
def _checked_settings(game_type, settings):
    initial_state = inspect.signature(game_type.initial_state)
    if settings is None:
        try:
            initial_state.bind(None, [])
        except TypeError:
            raise TypeError(
                f"{game_type.__name__}.initial_state needs settings. Give the "
                "LiveGameBarrier its settings."
            ) from None
        return None
    try:
        # A copy, as JSON has it, which is how the state will hold it.
        settings = json.loads(json.dumps(settings, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise TypeError(
            f"The settings for {game_type.__name__} can't be saved as JSON: {error}"
        ) from None
    try:
        initial_state.bind(None, [], settings)
    except TypeError:
        raise TypeError(
            f"{game_type.__name__}.initial_state takes no settings. Define it "
            "as initial_state(self, players, settings)."
        ) from None
    return settings


def live_session_id(participant, barrier_id):
    """Return the id of the session that a participant's group started at
    a :class:`LiveGameBarrier`, to read the session's result or its
    saved messages on a later page.

    Parameters
    ----------

    participant
        The participant.

    barrier_id
        The game barrier's ``id_``.

    Returns
    -------

    The session's id, or ``None`` if the group hasn't started a session
    there since the participant last arrived, for example because the group
    broke up while it waited.
    """
    return _live_session_ids(participant).get(barrier_id)


def _check_reached_barrier(participant, barrier_id):
    if barrier_id not in _live_session_ids(participant):
        raise ValueError(
            f"Participant {participant.id} hasn't reached a "
            f"LiveGameBarrier with the id {barrier_id!r}. Check the "
            "id, and that the page comes after that game barrier."
        )


def _live_session_ids(participant):
    return participant.live_sessions or {}


def _set_live_session_id(participant, barrier_id, session_id):
    # A new dict, which is what marks the column as changed.
    participant.live_sessions = {
        **_live_session_ids(participant),
        barrier_id: session_id,
    }
