"""PlayLiveGame, the timeline step where a group plays a live game, and
live_game_id, which finds the game.

PlayLiveGame resolves into a group barrier, which starts the game when
it releases the group, followed by the game page. The barrier stores the
game's id in each member's ``live_games``, keyed by the step's id, and
the page's LiveGameControl reads it from there. Reaching the barrier sets
that entry to ``None`` first, so the page finds only the game from the
participant's latest visit, and an id without an entry is one whose step the
participant never reached.

A PlayLiveGame in a trial also records the id on the trial's
SyncGroupRound, as ``live_game_id``, beside the outcome. That record
lasts, so it's the one to use in an analysis, while ``live_games`` holds
only each step's latest game, and is what the game page reads, including
for a game played outside a trial, which has no round.
"""

import inspect
import json

from dallinger.realtime import RealtimeGame, create_realtime_session

from ..barrier_spec import BarrierSpecError, barrier_spec_json
from ..bot import Bot
from ..modular_page import ModularPage
from ..sync import BarrierBehaviorMismatch, GroupBarrier
from ..timeline import CodeBlock, EltCollection, join
from ..utils import get_logger
from .game import LiveGame
from .psynet_entry import _new_session_settings

logger = get_logger()


class PlayLiveGame(EltCollection):
    """The step of the timeline where a group plays a live game.

    Like a :class:`~psynet.sync.GroupBarrier`, it first waits for every
    member of the participant's group to arrive. It then starts a game of
    ``game_class`` with the members as its players, and the group moves on
    together to ``page``, where they play it. A group that arrives again,
    for example in a loop, plays a new game.

    ::

        PlayLiveGame(
            group_type="pair",
            game_class=RockPaperScissors,
            page=ModularPage(
                "rock_paper_scissors",
                Prompt(tags.div(tags.p(id="status"), ...)),
                LiveGameControl(),
                js_page_modules=["/static/rock_paper_scissors.js"],
                time_estimate=30,
            ),
        )

    In a trial played in groups, return it from ``show_trial``: it is the
    group barrier that such a trial needs, and the game page's answer is the
    trial's answer.

    Parameters
    ----------

    group_type
        The ``group_type`` of the :class:`~psynet.sync.Grouper` whose groups
        play the game.

    game_class
        The game the group plays, a :class:`LiveGame` subclass with a
        ``bot`` method. Define it at the top level of a file, such as
        ``experiment.py``, not inside a function or another class.

    page
        The game page: a :class:`~psynet.modular_page.ModularPage` with a
        :class:`LiveGameControl`.

    settings
        Settings for the games this step starts, such as the number of
        rounds: a dict, or any other value that can be saved as JSON. The
        game's ``initial_state`` gets it as a second argument, so define
        that as ``initial_state(self, players, settings)``. In a trial's
        ``show_trial``, pass the trial's ``definition`` to play each trial's
        game with that trial's settings. The members of a group must all
        arrive with the same settings, so give the trial class, or its trial
        maker, the group's ``sync_group_type``, which gives them the same
        trial.

    on_release
        Optional function called when the wait ends and the group's game
        has been created, before its players' pages open, with the arguments
        that a :class:`~psynet.sync.GroupBarrier`'s ``on_release`` can take,
        such as ``trials`` and ``group_round``, and also ``live_game_id``,
        the new game's id. Use it for group bookkeeping at the start of a
        round, such as choosing who retires after it. ``live_game_id`` is
        ``None`` if no game started, because the group has fewer members than
        the game's ``min_players``.

    id_
        A name for this step, the game's ``channel`` unless given, which
        :func:`live_game_id` takes to find the group's game, for
        example on a later page. Steps with the same id share their wait,
        like barriers with the same id, so give a game that the timeline
        plays in two places, such as a practice game and the main game, a
        different id in each.

    **kwargs
        Any other parameter of :class:`~psynet.sync.GroupBarrier`, for the
        wait before the game, such as ``max_wait_time``, ``late_after`` or
        ``waiting_message``. A participant who has left the group passes
        the wait and reaches the game page without a game.
    """

    def __init__(
        self,
        group_type: str,
        game_class,
        page,
        settings=None,
        on_release=None,
        id_: str = None,
        **kwargs,
    ):
        from .control import LiveGameControl

        _check_game_class(game_class)
        if id_ is None:
            id_ = game_class.channel

        if not (
            isinstance(page, ModularPage) and isinstance(page.control, LiveGameControl)
        ):
            raise TypeError(
                f"The page of the PlayLiveGame {id_!r} must be a ModularPage "
                f"with a LiveGameControl, not {page!r}."
            )
        if page.control.game_id not in (None, id_):
            raise ValueError(
                f"The page given to the PlayLiveGame {id_!r} is already the page "
                f"of the PlayLiveGame {page.control.game_id!r}. Give each "
                "PlayLiveGame a page of its own."
            )
        page.control.game_id = id_
        self.barrier = _LiveGameBarrier(
            id_, group_type, game_class, settings, on_release, **kwargs
        )
        self.page = page

    def resolve(self):
        return join(self.barrier, self.page)


class _LiveGameBarrier(GroupBarrier):
    """The group barrier of a :class:`PlayLiveGame`, which starts the
    group's game when it releases the group. Its parameters are
    PlayLiveGame's, without ``page``."""

    def __init__(
        self,
        id_: str,
        group_type: str,
        game_class,
        settings=None,
        on_release=None,
        **kwargs,
    ):
        settings = _checked_settings(game_class, settings)
        super().__init__(
            id_=id_,
            group_type=group_type,
            on_release=_LiveGameBarrier._release,
            **kwargs,
        )
        self.game_class = game_class
        self.settings = settings
        self.on_game_release = on_release
        try:
            barrier_spec_json(self)
        except BarrierSpecError as error:
            raise TypeError(
                f"The PlayLiveGame {id_!r} can't be saved: {error}"
            ) from None

    def receive_participant(self, participant):
        try:
            return super().receive_participant(participant)
        except BarrierBehaviorMismatch:
            raise ValueError(
                f"Participant {participant.id} arrived at the "
                f"PlayLiveGame {self.id!r} with settings that differ "
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
        _set_live_game_id(participant, self.id, None)

    # The barrier's on_release has to be importable by name, and gets the
    # barrier rebuilt from its saved settings.
    @staticmethod
    def _release(
        group, participants, trials, group_round, leader, left, admitted, barrier
    ):
        session_id = barrier._start_session(participants, group_round)
        if barrier.on_game_release is not None:
            # Rebuilt from the barrier's saved settings, it passes each
            # function only the arguments it takes, as on_release does.
            barrier.on_game_release(
                group=group,
                participants=participants,
                trials=trials,
                group_round=group_round,
                leader=leader,
                participant=leader,
                left=left,
                admitted=admitted,
                barrier=barrier,
                live_game_id=session_id,
            )

    def _start_session(self, participants, group_round=None):
        game_class = self.game_class
        n_players = len(participants)
        if n_players < game_class.min_players:
            return None
        too_many = game_class.max_players is not None and (
            n_players > game_class.max_players
        )
        if too_many:
            # Logged rather than raised: an error while a group is released
            # is only logged anyway, and would leave the group waiting.
            logger.error(
                "A group of %d reached the PlayLiveGame %r, but %s has a "
                "max_players of %d, so it starts no game. Make the groups "
                "of its group type, %r, no larger than that.",
                n_players,
                self.id,
                game_class.__name__,
                game_class.max_players,
                self.group_type,
            )
            return None
        # In id order, which is the order the players signed up in, so a
        # game's initial_state and state["psynet"]["players"] list them
        # in that order.
        participants = sorted(participants, key=lambda member: member.id)
        token = _new_session_settings.set(self.settings)
        try:
            session_id = create_realtime_session(
                game_class,
                [member.id for member in participants],
                bots=[member.id for member in participants if isinstance(member, Bot)],
            )
        finally:
            _new_session_settings.reset(token)
        for member in participants:
            _set_live_game_id(member, self.id, session_id)
        if group_round is not None:
            group_round.live_game_id = session_id
        return session_id


def _check_game_class(game_class):
    if not (isinstance(game_class, type) and issubclass(game_class, LiveGame)):
        raise TypeError(f"game_class must be a LiveGame subclass, not {game_class!r}.")
    if game_class.channel is None:
        raise TypeError(
            f"{game_class.__name__} has no channel, so it can't be played. "
            "Set its channel to a name for the game."
        )
    if game_class.bot is RealtimeGame.bot:
        raise TypeError(
            f"{game_class.__name__} has no bot method, so its bots, such as "
            "those of psynet test, would never move. Define bot to return "
            "a bot's next message."
        )


# Checked when the timeline is built, since an error while a group is
# released is only logged, and leaves the group waiting.
def _checked_settings(game_class, settings):
    initial_state = inspect.signature(game_class.initial_state)
    if settings is None:
        try:
            initial_state.bind(None, [])
        except TypeError:
            raise TypeError(
                f"{game_class.__name__}.initial_state needs settings. Give the "
                "PlayLiveGame its settings."
            ) from None
        return None
    try:
        # A copy, as JSON has it, which is how the state will hold it.
        settings = json.loads(json.dumps(settings, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise TypeError(
            f"The settings for {game_class.__name__} can't be saved as JSON: {error}"
        ) from None
    try:
        initial_state.bind(None, [], settings)
    except TypeError:
        raise TypeError(
            f"{game_class.__name__}.initial_state takes no settings. Define it "
            "as initial_state(self, players, settings)."
        ) from None
    return settings


def live_game_id(participant, id_):
    """Return the id of the game that a participant's group played at a
    :class:`PlayLiveGame`, to read the game's result or its saved
    messages on a later page.

    Parameters
    ----------

    participant
        The participant.

    id_
        The PlayLiveGame's ``id_``, which is its game's ``channel`` unless it
        was given one.

    Returns
    -------

    The game's id, or ``None`` if the group hasn't started a game
    there since the participant last arrived, for example because the group
    broke up while it waited.
    """
    return _live_game_ids(participant).get(id_)


def _check_reached_game(participant, game_id):
    if game_id not in _live_game_ids(participant):
        raise ValueError(
            f"Participant {participant.id} hasn't reached the PlayLiveGame "
            f"{game_id!r}, whose game page they were shown. Only its "
            "barrier leads to the page, so check for anything that skips it."
        )


def _live_game_ids(participant):
    return participant.live_games or {}


def _set_live_game_id(participant, game_id, session_id):
    # A new dict, which is what marks the column as changed.
    participant.live_games = {
        **_live_game_ids(participant),
        game_id: session_id,
    }
