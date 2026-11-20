"""PlayLiveGame, the timeline step for solo and group live games, and
each participant's record of the games they played.

With group_type, PlayLiveGame resolves into a group barrier, which starts the game when
it releases the group, followed by the game page. The barrier stores the
game's id in each member's ``live_game_data``, keyed by the step's id, and
the page's LiveGameControl reads it from there, and saves the player's
answer beside it. Reaching the barrier sets the id to ``None`` first, so the
page finds only the game from the participant's latest visit, and a step
without a record is one the participant never reached. The record also keeps
every game the participant played at the step, with their answer in each,
its ``history``. Participant.live_games and live_game_history read it, as
LiveGameRecord objects.

Without a group, the timeline creates a session for the participant directly.
A solo prepared segment checks the trial cursor after each session and can open
a replacement session for the same pending trial.

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
    end_realtime_session,
)

from ..barrier_spec import BarrierSpecError, barrier_spec_json
from ..bot import Bot
from ..modular_page import ModularPage
from ..page import UnsuccessfulEndPage
from ..sync import BarrierBehaviorMismatch, GroupBarrier, _round_trial
from ..timeline import CodeBlock, EltCollection, conditional, join, while_loop
from ..utils import get_logger
from .game import LiveGame
from .psynet_entry import _new_session_settings
from .record import LiveGameRecord
from .trials import LiveTrialGame

logger = get_logger()


class PlayLiveGame(EltCollection):
    """Play a live game alone or with a group.

    With ``group_type``, as in a :class:`~psynet.sync.GroupBarrier`, it waits for every
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
        play the game. Omit for a game with exactly one player. A solo prepared
        segment resumes interrupted sessions until it completes or its open trial fails.

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
        trial. Alternatively supply a function accepting ``participants`` in seat
        order and returning JSON settings. It runs once during session creation
        and can load each player's assignments and prior answers.

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
        For group play, give the wait a limit, either ``late_after``, with ``late_action``,
        or ``max_wait_time``, as :ref:`the guide <live-games-wait>` explains. A
        participant who has left the group passes the wait and reaches the
        game page without a game.
    """

    def __init__(
        self,
        group_type: str | None = None,
        game_class=None,
        page=None,
        settings=None,
        on_release=None,
        join_running_game: bool = False,
        id_: str = None,
        **kwargs,
    ):
        from .control import LiveGameControl

        _check_game_class(game_class)
        if join_running_game and game_class.on_add is RealtimeGame.on_add:
            raise TypeError(
                f"{game_class.__name__} has no on_add method, so players can't "
                "join it while it runs. Define on_add to make room for a new "
                "player, or leave out join_running_game."
            )
        if id_ is None:
            id_ = game_class.name
        solo = group_type is None
        if solo and game_class.max_players != 1:
            raise ValueError("Omit group_type only for a game with exactly one player.")
        if solo and (on_release or join_running_game or kwargs):
            raise TypeError(
                "Group release, joining, and wait options require group_type."
            )
        if (
            not solo
            and kwargs.get("late_after") is None
            and kwargs.get("max_wait_time") is None
        ):
            raise TypeError(
                f"The PlayLiveGame {id_!r} needs a limit on its wait. Usually "
                'give it late_after, with late_action="leave_group", which '
                "moves on a member who keeps the others waiting, and a "
                "time_limit to the pages before it, which late_after allows "
                "for. Otherwise give it max_wait_time, which moves on the "
                "members who wait. Without either, a member still waiting "
                "after 20 seconds fails the experiment."
            )

        if not (
            isinstance(page, ModularPage) and isinstance(page.control, LiveGameControl)
        ):
            raise TypeError(
                f"The page of the PlayLiveGame {id_!r} must be a ModularPage "
                f"with a LiveGameControl, not {page!r}."
            )
        if page.control.play_id not in (None, id_):
            raise ValueError(
                f"The page given to the PlayLiveGame {id_!r} is already the page "
                f"of the PlayLiveGame {page.control.play_id!r}. Give each "
                "PlayLiveGame a page of its own."
            )
        page.control.play_id = id_
        self.page = page
        self.solo = _SoloLiveGame(id_, game_class, settings, page) if solo else None
        self.barrier = (
            None
            if solo
            else _LiveGameBarrier(
                id_,
                group_type,
                game_class,
                settings,
                on_release,
                join_running_game=join_running_game,
                names=page.control.names,
                **kwargs,
            )
        )

    def resolve(self):
        return self.solo.resolve() if self.solo else join(self.barrier, self.page)


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
        settings = (
            settings if callable(settings) else _checked_settings(game_class, settings)
        )
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
        """Raise an error if both the game and the trial it's played in pay
        for the game, which would pay each player twice."""
        from ..trial.main import Trial

        # Unwrapped, since PsyNet wraps each game's methods, its inherited
        # default included.
        game_pays = inspect.unwrap(self.game_class.performance_reward) is not (
            inspect.unwrap(LiveGame.performance_reward)
        )
        trial_pays = (
            type(trial).compute_performance_reward
            is not Trial.compute_performance_reward
        )
        if game_pays and trial_pays:
            raise TypeError(
                f"{type(trial).__name__} pays through compute_performance_reward, "
                f"and its game, {self.game_class.__name__}, through "
                "performance_reward, so each player would be paid twice. Pay "
                "in one of them: in the trial when what the game pays depends "
                "on the trial's definition, and otherwise in the game."
            )

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
        if row is None or participant.id in row.members:
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
        settings = (
            self.settings(participants=participants)
            if callable(self.settings)
            else self.settings
        )
        session_id = _create_game_session(game_class, participants, settings)
        for member in participants:
            _set_live_game_id(member, self.id, session_id)
        if group_round is not None:
            group_round.live_game_id = session_id
        return session_id


def _create_game_session(game_class, participants, settings):
    if issubclass(game_class, LiveTrialGame):
        settings = game_class._session_settings(participants, settings)
    token = _new_session_settings.set(_checked_settings(game_class, settings))
    try:
        return create_realtime_session(
            game_class,
            [member.id for member in participants],
            bots=[member.id for member in participants if isinstance(member, Bot)],
        )
    finally:
        _new_session_settings.reset(token)


def _end_expired_session(session_id):
    try:
        end_realtime_session(session_id, "response_timeout")
    except KeyError:
        # The runner has already discarded the interrupted session.
        pass


class _SoloLiveGame:
    """Start directly on the participant timeline. Prepared segments can span sessions."""

    def __init__(self, id_, game_class, settings, page):
        self.id = id_
        self.game_class = game_class
        self.settings = (
            settings if callable(settings) else _checked_settings(game_class, settings)
        )
        self.page = page

    def _settings(self, participant):
        return (
            self.settings(participants=[participant])
            if callable(self.settings)
            else self.settings
        )

    def _start(self, participant):
        self._open(participant, self._settings(participant))

    def _open(self, participant, settings):
        session_id = _create_game_session(self.game_class, [participant], settings)
        _set_live_game_id(
            participant, self.id, session_id, names=self.page.control.names
        )
        return session_id

    def _prepare(self, participant):
        run = participant.module_state
        trials = self.game_class._active_maker(participant).prepare_trials(participant)
        settings = self._settings(participant)
        if settings is not None and not isinstance(settings, dict):
            raise ValueError("LiveTrialGame settings must be a dictionary.")
        settings = dict(settings or {})
        stop = settings.get("stop")
        if stop is None:
            stop = len(trials)
        if type(stop) is not int or not sum(t.complete for t in trials) <= stop <= len(
            trials
        ):
            raise ValueError("stop must be within the remaining prepared sequence.")
        # The session indexes this deck from zero. Trial.position counts across blocks.
        start_position = trials[0].position if trials else run.n_completed_trials
        run.var.solo_trial_segment = {
            "settings": {**settings, "stop": stop},
            "end_position": start_position + stop,
        }
        _set_live_game_id(participant, self.id, None, names=self.page.control.names)

    def _completed(self, participant):
        run = participant.module_state
        return run.n_completed_trials == run.var.solo_trial_segment["end_position"]

    def _pending(self, participant):
        from ..trial.static import StaticTrial

        if self._completed(participant) or participant.failed:
            return False
        run = participant.module_state
        trial = (
            StaticTrial.query.filter_by(
                module_state_id=run.id,
                block_position=run.block_position,
                position=run.n_completed_trials,
            )
            .with_for_update()
            .populate_existing()
            .one()
        )
        if trial.failed or trial._expire_if_overdue():
            return False
        record = participant.live_games[self.id]
        return record.id is None or record.end_reason in (
            "players_left",
            "not_joined",
            "timeout",
        )

    def _start_segment(self, participant):
        run = participant.module_state
        run.var.solo_trial_session = self._open(
            participant, run.var.solo_trial_segment["settings"]
        )

    def resolve(self):
        if not issubclass(self.game_class, LiveTrialGame):
            start = CodeBlock(self._start)
            start.links["solo_live_game"] = self.id
            return join(start, self.page)
        prepare = CodeBlock(self._prepare)
        prepare.links["solo_live_game"] = self.id
        return join(
            prepare,
            while_loop(
                f"{self.id}_pending",
                self._pending,
                join(CodeBlock(self._start_segment), self.page),
                expected_repetitions=1,
            ),
            conditional(
                f"{self.id}_incomplete",
                lambda participant: not self._completed(participant),
                UnsuccessfulEndPage(failure_tags=["incomplete_trial_segment"]),
            ),
        )


def _check_game_class(game_class):
    if not (isinstance(game_class, type) and issubclass(game_class, LiveGame)):
        raise TypeError(f"game_class must be a LiveGame subclass, not {game_class!r}.")
    if game_class.name is None:
        raise TypeError(
            f"{game_class.__name__} has no name, so it can't be played. "
            'Set its name, such as name = "rock_paper_scissors".'
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


def _live_game_id(participant, play_id):
    """Return the id of the participant's latest game at the PlayLiveGame
    ``play_id``, or None."""
    return _live_game_data(participant).get(play_id, {}).get("id")


def _check_reached_game(participant, play_id):
    if play_id not in _live_game_data(participant):
        raise ValueError(
            f"Participant {participant.id} hasn't reached the PlayLiveGame "
            f"{play_id!r}, whose game page they were shown. Only its "
            "start step leads to the page, so check for anything that skips it."
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
