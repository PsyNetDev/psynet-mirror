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

With ``absent_action``, the record also keeps the group types a player who
doesn't play the game leaves, which the job that saves the game's ending
reads, since the absent player may never make another request.

A PlayLiveGame in a trial also records the id on the trial's
SyncGroupRound, as ``live_game_id``, beside the outcome. That record
lasts, so it's the one to use in an analysis, while ``live_game_data`` holds
only each step's latest game, and is what the game page reads, including
for a game played outside a trial, which has no round.
"""

import inspect
import json
from typing import Optional

from dallinger import db
from dallinger.models import RealtimeSession
from dallinger.realtime import (
    RealtimeGame,
    add_realtime_player,
    create_realtime_session,
)

from ..barrier_spec import BarrierSpecError, barrier_spec_json
from ..bot import Bot
from ..sync import (
    BarrierBehaviorMismatch,
    GroupBarrier,
    ParticipantLinkSyncGroup,
    _lock_sync_group,
    _round_trial,
    _validate_group_timeouts,
)
from ..timeline import CodeBlock, EltCollection, conditional, join
from ..utils import get_logger
from .game import LiveGame
from .psynet_entry import _new_session
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
        rounds: any value that can be saved as JSON, which the game's
        ``initial_state(self, players, settings)`` gets. In a trial's
        ``show_trial``, pass the trial's ``definition``. The members of a
        group must all arrive with the same settings.

    on_release
        Optional function called when the wait ends and the group's game
        has been created, before its players' pages open, with the arguments
        that a :class:`~psynet.sync.GroupBarrier`'s ``on_release`` can take,
        such as ``trials`` and ``group_round``, and also ``live_game``,
        the new game's :class:`LiveGameRecord`, whose ``status`` is
        ``"not_started"`` if no game started.

    join_running_game
        Whether a member who reaches the step while their group is playing
        a game from it joins that game, rather than waiting for the group's
        next game. The game must define ``on_add``, and the group's
        :class:`~psynet.sync.Grouper` needs ``join_existing_groups=True``. A
        game can stop taking players through its
        :meth:`~LiveGame.accepts_players`. A game played in a trial can't
        take newcomers (see :ref:`live-games-join-and-finish`). Default:
        ``False``.

    absent_action
        ``"leave_group"`` to remove a player who didn't play the game, a
        no-show or, with the game's :attr:`~LiveGame.away_timeout`, one who
        left it for good, from the step's group and the groups in
        ``also_leave`` once the game's result is saved. Their
        :meth:`~psynet.participant.Participant.sync_group_removal_reason`
        is then ``"no_show"`` or ``"left_game"``. Those groups' groupers
        need ``below_quorum="continue_without_group"``
        (see :ref:`live-games-absent`). Default: ``None``, which leaves them
        in their groups.

    stop_top_ups_at_end
        Whether the group stops taking newcomers, as
        :meth:`~psynet.sync.SimpleSyncGroup.stop_top_ups` does, once each
        game it plays here has ended, so nobody joins a group whose game is
        over. It only affects a group whose grouper has
        ``join_existing_groups=True``. Set it to ``False`` for a group that
        takes newcomers for the next game it plays. Default: ``True``.

    id_
        A name for this step, the game's ``name`` unless given, which
        keys the participant's :attr:`~psynet.participant.Participant.live_games`
        and :attr:`~psynet.participant.Participant.live_game_history`. Steps
        with the same id share their wait, like barriers with the same id, so
        give a game that the timeline plays in two places a different id in
        each.

    **kwargs
        Any other parameter of :class:`~psynet.sync.GroupBarrier`, for the
        wait before the game, such as ``late_after`` or ``waiting_message``.
        Give the wait a limit, ``late_after`` with ``late_action``, or
        ``max_wait_time`` (see :ref:`the wait before the game <live-games-wait>`). Its ``also_leave``
        applies to ``absent_action`` as well as to ``late_action``.
    """

    def __init__(
        self,
        group_type: str,
        game_class,
        page,
        settings=None,
        on_release=None,
        join_running_game: bool = False,
        absent_action: Optional[str] = None,
        stop_top_ups_at_end: bool = True,
        id_: str = None,
        **kwargs,
    ):
        from .control import LiveGamePage

        _check_game_class(game_class)
        if absent_action not in (None, "leave_group"):
            raise ValueError(
                f"absent_action must be 'leave_group' or None, not {absent_action!r}."
            )
        also_leave = kwargs.get("also_leave") or []
        if absent_action is not None and kwargs.get("late_action") != "leave_group":
            # Only the players who don't play leave those groups, so the
            # barrier, which would refuse them, doesn't get them.
            kwargs.pop("also_leave", None)
            _validate_group_timeouts(
                "fail", None, "leave_group", also_leave, group_type
            )
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
            stop_top_ups_at_end=stop_top_ups_at_end,
            names=page.control.names,
            absent_leave=(
                [group_type, *also_leave] if absent_action == "leave_group" else []
            ),
            **kwargs,
        )
        self.page = page

    def resolve(self):
        return join(CodeBlock(self._save_player_info), self.barrier, self.page)

    def _save_player_info(self, participant):
        # Saved on each visit, so a later page without player_info doesn't
        # show what an earlier one gave.
        player_info = self.page.control.player_info
        info = None if player_info is None else player_info(participant)
        try:
            info = json.loads(json.dumps(info, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise TypeError(
                f"The player_info of the PlayLiveGame {self.barrier.id!r}'s "
                f"page returned {info!r}, which can't be saved as JSON: {error}"
            ) from None
        data = _live_game_data(participant).get(self.barrier.id, {})
        _set_data(participant, self.barrier.id, {**data, "info": info})


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
        stop_top_ups_at_end=True,
        names="shown",
        absent_leave=(),
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
        self.stop_top_ups_at_end = bool(stop_top_ups_at_end)
        # The game page's names, kept with each member's game, so that the
        # players route sends pseudonyms only to pages that show them.
        self.names = names
        # The group types a player who doesn't play the game leaves, kept with
        # each member's game too, for the job that saves the game's result.
        self.absent_leave = list(absent_leave)
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
        _set_live_game_id(
            participant,
            self.id,
            None,
            names=self.names,
            absent_leave=self.absent_leave,
        )
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
        row = (
            _running_game_query(members, self.id)
            .with_for_update()
            .populate_existing()
            .first()
        )
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
        # seconds later, so the members playing it count too, read once the
        # row is locked to see those whom other requests have just added.
        players = set(row.members) | _members_playing(group, self.id, row.id)
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
        token = _new_session.set(
            {
                "settings": self.settings,
                "group_id": group.id,
                "stop_top_ups_at_end": self.stop_top_ups_at_end,
            }
        )
        try:
            session_id = create_realtime_session(
                game_class,
                [member.id for member in participants],
                bots=[member.id for member in participants if isinstance(member, Bot)],
            )
        finally:
            _new_session.reset(token)
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
    played there, as ``{"id": game_id, "answer": answer}``, oldest first, its
    game page's ``names``, ``"shown"`` or ``"anonymous"``, the group types
    a player who doesn't play leaves, its ``absent_leave``, and what its
    page's ``player_info`` gave, its ``info``."""
    return participant.live_game_data or {}


def _set_live_game_id(participant, play_id, game_id, names=None, absent_leave=None):
    data = _live_game_data(participant).get(play_id, {})
    history = list(data.get("history", []))
    if game_id is not None and all(game["id"] != game_id for game in history):
        history.append({"id": game_id, "answer": None})
    names = names or data.get("names", "shown")
    if absent_leave is None:
        absent_leave = data.get("absent_leave", [])
    _set_data(
        participant,
        play_id,
        {
            "id": game_id,
            "history": history,
            "names": names,
            "absent_leave": absent_leave,
            "info": data.get("info"),
        },
    )


def _player_info(participant, play_id):
    """Return what the participant's game page's ``player_info`` gave when
    they last reached the PlayLiveGame ``play_id``, or None."""
    return _live_game_data(participant).get(play_id, {}).get("info")


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


def _members_playing(group, play_id, game_id):
    """Return the ids of the group's members whose latest game at the
    PlayLiveGame ``play_id`` is ``game_id``, read from the database rather
    than from the members the caller's database session already loaded.

    Members who have since failed or left the group still count: they were
    added to the game, and Dallinger counts them against ``max_players``
    once it writes them to the game's ``members``.
    """
    from ..participant import Participant

    rows = (
        db.session.query(Participant.id, Participant.live_game_data)
        .join(
            ParticipantLinkSyncGroup,
            ParticipantLinkSyncGroup.participant_id == Participant.id,
        )
        .filter(ParticipantLinkSyncGroup.sync_group_id == group.id)
    )
    return {
        participant_id
        for participant_id, data in rows
        if ((data or {}).get(play_id) or {}).get("id") == game_id
    }


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


def _remove_absent_players(game, session_row, players):
    """Remove the ``players`` who didn't play the game from the groups their
    PlayLiveGame's ``absent_action`` names, with the reasons that
    LiveGame.absences gives for the final state.

    Called as the game's ending is saved, with the players' rows locked. They
    all leave before any group is dissolved below its quorum, so a pair of
    no-shows both leave as no-shows. Each group's row is locked, in id
    order, and its members reloaded first, so that sibling games sharing a
    group (``also_leave``) and ending at once each count the other's leavers.
    """
    state = session_row.final_state
    if (state or {}).get("psynet") is None:
        return
    leaves_by_player = [
        (participant, _absent_leave(participant, session_row.id))
        for participant in players
    ]
    if not any(leaves for _, leaves in leaves_by_player):
        return
    absences = game.absences(state)
    leaving = []
    for participant, leaves in leaves_by_player:
        player = state["psynet"]["participant_ids"].index(participant.id)
        # Players who came too late are numbered last, and have no absence.
        reason = absences[player] if player < len(absences) else None
        if not leaves or reason is None:
            continue
        groups = participant.active_sync_groups
        for group_type in leaves:
            if group_type in groups:
                leaving.append((participant, reason, groups[group_type].id))
    groups = {
        group_id: _lock_sync_group_and_links(group_id)
        for group_id in sorted({group_id for _, _, group_id in leaving})
    }
    left = {}
    for participant, reason, group_id in leaving:
        group = groups[group_id]
        if group.active and group._active_link(participant) is not None:
            group._remove_without_quorum_check(participant, reason)
            left[group_id] = group
    for group in left.values():
        group.dissolve_if_below_quorum()


def _stop_top_ups_soon(group_id):
    """Stop the group of id ``group_id``, a game's, taking newcomers, in a
    job of its own once the current transaction commits. A game's record is
    written in one transaction, which locks its players' rows, and a group's
    row has to be locked after its members' rows, never before."""
    from ..async_job import WorkerAsyncJob

    if group_id is not None:
        WorkerAsyncJob(
            _stop_top_ups,
            arguments={"group_id": group_id},
            label="stop_live_game_top_ups",
        ).enqueue()


def _stop_top_ups(group_id):
    """Stop the group of id ``group_id``, a game's, taking newcomers, as
    SimpleSyncGroup.stop_top_ups does, if it still does. ``group_id`` is
    None for a game that a PlayLiveGame didn't start."""
    if group_id is None:
        return
    group = _lock_sync_group_and_links(group_id)
    if group is not None and group.active and group.accepts_top_ups:
        group.stop_top_ups()


def _lock_sync_group_and_links(group_id):
    """Lock a sync group's row and reload its member links, which this
    transaction may have loaded before another committed changes to them."""
    group = _lock_sync_group(group_id)
    (
        db.session.query(ParticipantLinkSyncGroup)
        .filter_by(sync_group_id=group_id)
        .populate_existing()
        .all()
    )
    return group


def _absent_leave(participant, game_id):
    """Return the group types the participant leaves if they don't play the
    game ``game_id``, from the PlayLiveGame that started it."""
    for data in _live_game_data(participant).values():
        if any(game["id"] == game_id for game in data.get("history", [])):
            return data.get("absent_leave", [])
    return []
