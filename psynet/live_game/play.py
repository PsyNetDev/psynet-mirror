"""PlayLiveGame, the timeline step where a group plays a live game, and
each participant's record of the games they played.

PlayLiveGame resolves into a group barrier, which starts the game when
it releases the group, followed by the game page. The barrier stores the
game's id in each member's ``live_game_data``, keyed by the step's id, and
the game page reads it from there, and saves the player's
answer beside it. Reaching the barrier sets the id to ``None`` first, so the
page finds only the game from the participant's latest visit, and a step
without a record is one the participant never reached. The record also keeps
every game the participant played at the step, with their answer in each,
its ``history``. Participant.live_games and live_game_history read it, as
LiveGameRecord objects.

With ``join_running_game``, a participant whose group is playing a game
from the step is added to that game instead, and skips the barrier.

A PlayLiveGame in a trial also records the id on the trial's
SyncGroupRound, as ``live_game_id``, beside the outcome. That record
lasts, so it's the one to use in an analysis, while ``live_game_data`` holds
only each step's latest game, and is what the game page reads, including
for a game played outside a trial, which has no round.
"""

import inspect
import json

from dallinger import db
from dallinger.models import RealtimeSession
from dallinger.realtime import (
    RealtimeGame,
    add_realtime_player,
    create_realtime_session,
)

from ..barrier_spec import BarrierSpecError, barrier_spec_json
from ..bot import Bot
from ..sync import BarrierBehaviorMismatch, GroupBarrier, _round_trial
from ..timeline import CodeBlock, EltCollection, conditional, join
from ..utils import get_logger
from .game import LiveGame
from .psynet_entry import _new_session_settings
from .record import LiveGameRecord, _player_ending

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
            settings={"throws": 5, "reward_per_win": 0.05},
            page=LiveGamePage(
                "rock_paper_scissors",
                tags.div(tags.p(id="status"), ...),
                js_page_modules=["/static/rock-paper-scissors.js"],
                time_estimate=30,
            ),
            late_after=30,
            late_action="leave_group",
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
        The game page, a :class:`LiveGamePage`.

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
        such as ``trials`` and ``group_round``, and also ``live_game``,
        the new game's :class:`LiveGameRecord`. Use it for group bookkeeping
        at the start of a round, such as choosing who retires after it. The
        record's ``status`` is ``"not_started"`` if no game started, because
        the group has fewer members than the game's ``min_players``.

    join_running_game
        Whether a member who reaches the step while their group is playing
        a game from it joins that game, rather than waiting at the barrier
        for the group's next game. The game must define ``on_add``, as
        :ref:`live-games-join-and-finish` explains. Newcomers join a group,
        and so its game, only with a :class:`~psynet.sync.Grouper` that has
        ``join_existing_groups=True``. A game played in a trial can't take
        newcomers, since its round is already under way. Default: ``False``.

    id_
        A name for this step, the game's ``name`` unless given, which
        keys the participant's :attr:`~psynet.participant.Participant.live_games`
        and :attr:`~psynet.participant.Participant.live_game_history`, for example to read the game's
        answer on a later page. Steps with the same id share their wait,
        like barriers with the same id, so give a game that the timeline
        plays in two places, such as a practice game and the main game, a
        different id in each.

    **kwargs
        Any other parameter of :class:`~psynet.sync.GroupBarrier`, for the
        wait before the game, such as ``late_after`` or ``waiting_message``.
        Give the wait a limit, either ``late_after``, with ``late_action``,
        or ``max_wait_time``, as :ref:`the guide <live-games-wait>` explains. A
        participant who has left the group passes the wait and reaches the
        game page without a game.
    """

    def __init__(
        self,
        group_type: str,
        game_class,
        page,
        settings=None,
        on_release=None,
        join_running_game: bool = False,
        id_: str = None,
        **kwargs,
    ):
        from .control import LiveGamePage

        _check_game_class(game_class)
        if join_running_game and game_class.on_add is RealtimeGame.on_add:
            raise TypeError(
                f"{game_class.__name__} has no on_add method, so players can't "
                "join it while it runs. Define on_add to make room for a new "
                "player, or leave out join_running_game."
            )
        if id_ is None:
            id_ = game_class.name
        if kwargs.get("late_after") is None and kwargs.get("max_wait_time") is None:
            raise TypeError(
                f"The PlayLiveGame {id_!r} needs a limit on its wait. Usually "
                'give it late_after, with late_action="leave_group", which '
                "moves on a member who keeps the others waiting, and a "
                "time_limit to the pages before it, which late_after allows "
                "for. Otherwise give it max_wait_time, which moves on the "
                "members who wait. Without either, a member still waiting "
                "after 20 seconds fails the experiment."
            )

        if not isinstance(page, LiveGamePage):
            raise TypeError(
                f"The page of the PlayLiveGame {id_!r} must be a LiveGamePage, "
                f"not {page!r}."
            )
        if page.control.play_id not in (None, id_):
            raise ValueError(
                f"The page given to the PlayLiveGame {id_!r} is already the page "
                f"of the PlayLiveGame {page.control.play_id!r}. Give each "
                "PlayLiveGame a page of its own."
            )
        page.control.play_id = id_
        self.barrier = _LiveGameBarrier(
            id_,
            group_type,
            game_class,
            settings,
            on_release,
            join_running_game=join_running_game,
            names=page.control.names,
            **kwargs,
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
        join_running_game=False,
        names="shown",
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
        self.join_running_game = join_running_game
        # The game page's names, kept with each member's game, so that the
        # players route sends pseudonyms only to pages that show them.
        self.names = names
        try:
            barrier_spec_json(self)
        except BarrierSpecError as error:
            raise TypeError(
                f"The PlayLiveGame {id_!r} can't be saved: {error}"
            ) from None

    def _check_trial(self, trial):
        """Raise an error if the trial plays a game other than the one its
        class names, or if both the game and the trial pay for the game."""
        trial_class = type(trial)
        named = trial_class.live_game_class
        if named is not None and named is not self.game_class:
            raise TypeError(
                f"{trial_class.__name__}.live_game_class is {named.__name__}, "
                f"but its show_trial plays {self.game_class.__name__}. Set "
                "live_game_class to the game the trial plays."
            )
        _check_paid_once(trial_class, self.game_class)

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
        arrive = CodeBlock(self._arrive)
        if not self.join_running_game:
            return join(arrive, super().resolve())
        return join(
            arrive,
            conditional(
                f"{self.id}_no_running_game",
                lambda participant: _live_game_id(participant, self.id) is None,
                super().resolve(),
            ),
        )

    def _arrive(self, participant):
        _set_live_game_id(participant, self.id, None, names=self.names)
        if self.join_running_game:
            self._join_running_game(participant)

    def _join_running_game(self, participant):
        """Add the participant to their group's running game from this
        step, if there is one with room for them."""
        group = participant.active_sync_groups.get(self.group_type)
        if group is None:
            return
        trial = _round_trial(group, participant)
        if trial is not None and not trial.complete:
            raise ValueError(
                f"The PlayLiveGame {self.id!r} has join_running_game, but "
                f"participant {participant.id} reached it in a trial. A game "
                "played in a trial can't take newcomers, since its round is "
                "already under way. Play the game outside a trial."
            )
        members = group.active_participants
        if participant not in members:
            return
        # Locked, so players added at the same time are counted against
        # max_players one after the other.
        row = _running_game_query(members, self.id).with_for_update().first()
        if row is None:
            return
        if participant.id in row.members:
            # Already a player, for example after a retried request: they go
            # back to the game unless their part of it has ended.
            if _player_ending(row.id, participant.id) is None:
                _set_live_game_id(participant, self.id, row.id)
            return
        max_players = self.game_class.max_players
        # The row lists a newcomer only once their addition is written, a few
        # seconds later, so the members playing it count too.
        players = set(row.members) | {
            member.id for member in members if _live_game_id(member, self.id) == row.id
        }
        if max_players is not None and len(players) >= max_players:
            return
        add_realtime_player(row.id, participant, bot=isinstance(participant, Bot))
        _set_live_game_id(participant, self.id, row.id)

    # The barrier's on_release has to be importable by name, and gets the
    # barrier rebuilt from its saved settings.
    @staticmethod
    def _release(
        group, participants, trials, group_round, leader, left, admitted, barrier
    ):
        session_id = barrier._start_session(participants, group, group_round)
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
                live_game=LiveGameRecord(session_id),
            )

    def _start_session(self, participants, group, group_round=None):
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
        # Numbered in seat order, as GroupPrompt shows the group's members,
        # so a player's number gives away no more than the group's other
        # pages do.
        seats = group.seats
        participants = sorted(participants, key=lambda member: seats[member.id])
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


def _check_game_class(game_class, label="game_class"):
    """Check that ``game_class``, named ``label`` in errors, is a game that can
    be played."""
    if not (isinstance(game_class, type) and issubclass(game_class, LiveGame)):
        raise TypeError(f"{label} must be a LiveGame subclass, not {game_class!r}.")
    if game_class.name is None:
        raise TypeError(
            f"{label} is {game_class.__name__}, which has no name, so it can't "
            'be played. Set its name, such as name = "rock_paper_scissors".'
        )
    if game_class.bot is RealtimeGame.bot:
        raise TypeError(
            f"{label} is {game_class.__name__}, which has no bot method, so "
            "its bots, such as those of psynet test, would never move. "
            "Define bot to return a bot's next message."
        )


def _check_trial_class(trial_class):
    """Check the game a trial class names in its ``live_game_class``, when
    the class is defined."""
    game_class = trial_class.live_game_class
    _check_game_class(game_class, label=f"{trial_class.__name__}.live_game_class")
    _check_paid_once(trial_class, game_class)


def _check_paid_once(trial_class, game_class):
    """Raise an error if both a trial class and the game played in its
    trials pay for the game, which would pay each player twice."""
    from ..trial.main import Trial

    # Unwrapped, since PsyNet wraps each game's methods, its inherited
    # default included.
    game_pays = inspect.unwrap(game_class.performance_reward) is not (
        inspect.unwrap(LiveGame.performance_reward)
    )
    trial_pays = (
        trial_class.compute_performance_reward is not Trial.compute_performance_reward
    )
    if game_pays and trial_pays:
        raise TypeError(
            f"{trial_class.__name__} pays through compute_performance_reward, "
            f"and its game, {game_class.__name__}, through "
            "performance_reward, so each player would be paid twice. Pay "
            "in one of them, preferably the game, which also pays a "
            "player who leaves the game page for good. Pass any of the "
            "trial's definition the reward needs in the game's settings."
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


def _live_game_id(participant, play_id):
    """Return the id of the participant's latest game at the PlayLiveGame
    ``play_id``, or None."""
    return _live_game_data(participant).get(play_id, {}).get("id")


def _check_reached_game(participant, play_id):
    if play_id not in _live_game_data(participant):
        raise ValueError(
            f"Participant {participant.id} hasn't reached the PlayLiveGame "
            f"{play_id!r}, whose game page they were shown. Only its "
            "barrier leads to the page, so check for anything that skips it."
        )


def _live_game_data(participant):
    """Return what PsyNet stored about each PlayLiveGame the participant
    reached, keyed by its id: the ``id`` of their latest game there, or None
    if their group didn't start one, the ``history`` of every game they
    played there, as ``{"id": game_id, "answer": answer}``, oldest first, and
    its game page's ``names``, ``"shown"`` or ``"anonymous"``."""
    return participant.live_game_data or {}


def _set_live_game_id(participant, play_id, game_id, names=None):
    data = _live_game_data(participant).get(play_id, {})
    history = list(data.get("history", []))
    if game_id is not None and all(game["id"] != game_id for game in history):
        history.append({"id": game_id, "answer": None})
    names = names or data.get("names", "shown")
    _set_data(participant, play_id, {"id": game_id, "history": history, "names": names})


def _set_live_game_answer(participant, play_id, answer):
    data = _live_game_data(participant)[play_id]
    history = [
        {**game, "answer": answer} if game["id"] == data["id"] else game
        for game in data["history"]
    ]
    _set_data(participant, play_id, {**data, "history": history})


def _set_data(participant, play_id, data):
    # A new dict, which is what marks the column as changed.
    participant.live_game_data = {**_live_game_data(participant), play_id: data}


def _participant_live_games(participant):
    """Return Participant.live_games."""
    return {
        play_id: LiveGameRecord(data.get("id"), participant)
        for play_id, data in _live_game_data(participant).items()
    }


def _participant_live_game_history(participant):
    """Return Participant.live_game_history."""
    return {
        play_id: [
            LiveGameRecord(game["id"], participant) for game in data.get("history", [])
        ]
        for play_id, data in _live_game_data(participant).items()
    }


def _running_game_query(members, play_id):
    """Return a query for the running game, if any, that the group's
    ``members`` played at the PlayLiveGame ``play_id``, newest first."""
    game_ids = {_live_game_id(member, play_id) for member in members} - {None}
    return (
        db.session.query(RealtimeSession)
        .filter(
            RealtimeSession.id.in_(game_ids),
            RealtimeSession.status == "running",
        )
        .order_by(RealtimeSession.id.desc())
    )


def _running_live_games(group):
    """Return SyncGroup.running_live_games."""

    members = group.active_participants
    play_ids = {
        play_id
        for member in members
        for play_id, data in _live_game_data(member).items()
        if data.get("id") is not None
    }
    running = {}
    for play_id in sorted(play_ids):
        row = _running_game_query(members, play_id).first()
        if row is not None:
            running[play_id] = LiveGameRecord(row.id)
    return running
