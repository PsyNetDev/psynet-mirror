"""What PsyNet does with a live game's record as Dallinger writes it: the
rewards from add_performance_reward, paid by effects queued during the game,
the reward from the outcome of a player whose game ends before the game
does, and, once the result is saved, the other players' rewards from the
outcome and the copy of the outcome on the game's round. A reward is also recorded on the trial
the game was played in, if any. All run in the job that writes the game's
record, so each runs once, whether or not the players are still on the game
page."""

import functools

from dallinger import db
from dallinger.models import timenow
from dallinger.realtime.utils import is_number

from .history import _MOMENT_EFFECT
from .messages import _STARTED_EFFECT
from .record import _has_outcome, _players_ended_early

# The name of the effect add_performance_reward queues.
_REWARD_EFFECT = "psynet_performance_reward"


def _check_reward(amount, what):
    if not is_number(amount) or amount < 0:
        raise ValueError(
            f"{what} gave the reward {amount!r}. A reward must be a number "
            "of 0 or more."
        )
    # A NumPy number, for example, can't go into JSON or Postgres as it is.
    return float(amount)


def _add_reward(participant, amount, session_row):
    if not amount:
        return
    participant.inc_performance_reward(amount)
    trial = _lock_trial_played_in(participant, session_row)
    if trial is not None:
        trial._record_performance_reward(amount)


def _lock_trial_played_in(participant, session_row):
    """Return the participant's trial in the round the game was played
    in, locked for update, if the game was played as a trial: their latest in
    the round, which is the one whose show_trial started the game."""
    from ..sync import SyncGroupRound
    from ..trial.main import Trial

    return (
        db.session.query(Trial)
        .join(SyncGroupRound, Trial.sync_group_round_id == SyncGroupRound.id)
        .filter(
            SyncGroupRound.live_game_id == session_row.id,
            Trial.participant_id == participant.id,
        )
        .order_by(Trial.id.desc())
        .with_for_update(of=Trial)
        .populate_existing()
        .first()
    )


def _locked_players(session_row, participant_ids=None):
    """Return the game's players, or those of ``participant_ids``, locked so
    a reward isn't lost to a request changing a participant at the same
    time. They are locked in id order, so a job paying several of them can't
    deadlock with another transaction locking them in a different order."""
    from ..participant import Participant

    if participant_ids is None:
        participant_ids = session_row.members
    return (
        db.session.query(Participant)
        .filter(Participant.id.in_(participant_ids))
        .order_by(Participant.id)
        .with_for_update(of=Participant)
        .populate_existing()
        .all()
    )


def _handles_reward(method):
    @functools.wraps(method)
    def handle_effect(self, name, payload, session_row):
        if name in (_STARTED_EFFECT, _MOMENT_EFFECT):
            # Only recorded, for a game record's messages and moments.
            return None
        if name != _REWARD_EFFECT:
            return method(self, name, payload, session_row)
        player = payload["player"]
        participant_ids = _participant_ids(session_row)
        if player >= len(participant_ids):
            raise ValueError(
                f"{type(self).__name__}.add_performance_reward gave a reward to "
                f"player {player}, but game {session_row.id} has only "
                f"{len(participant_ids)} players, numbered from 0."
            )
        players = _locked_players(session_row)
        (participant,) = [p for p in players if p.id == participant_ids[player]]
        _add_reward(participant, payload["amount"], session_row)

    handle_effect._psynet_wrapper = True
    return handle_effect


def _handles_ending(method):
    @functools.wraps(method)
    def handle_ending(self, session_row):
        players = _locked_players(session_row)
        if _has_outcome(session_row.status, session_row.outcome):
            _pay_outcome_rewards(self, session_row, players)
            _record_outcome_on_round(session_row)
        _end_game_page_deadlines(session_row, players, session_row.end_time)
        return method(self, session_row)

    handle_ending._psynet_wrapper = True
    return handle_ending


def _handles_player_ending(method):
    @functools.wraps(method)
    def handle_player_ending(self, session_row, player_id, ending):
        (participant,) = _locked_players(session_row, [int(player_id)])
        player = _participant_ids(session_row).index(participant.id)
        amount = self.performance_reward(ending["outcome"], ending["reason"], player)
        what = f"{type(self).__name__}.performance_reward"
        _add_reward(participant, _check_reward(amount, what), session_row)
        _end_game_page_deadlines(session_row, [participant], timenow())
        return method(self, session_row, player, ending)

    handle_player_ending._psynet_wrapper = True
    return handle_player_ending


def _participant_ids(session_row):
    """Return the participant ids of a game's players, in player order."""
    return [int(member) for member in session_row.members]


def _pay_outcome_rewards(game, session_row, players):
    what = f"{type(game).__name__}.performance_reward"
    participant_ids = _participant_ids(session_row)
    # Paid when their own game ended.
    ended_early = _players_ended_early(session_row.id)
    for participant in players:
        if participant.id in ended_early:
            continue
        amount = game.performance_reward(
            session_row.outcome,
            session_row.end_reason,
            participant_ids.index(participant.id),
        )
        _add_reward(participant, _check_reward(amount, what), session_row)


def _end_game_page_deadlines(session_row, players, ended):
    """Move the players' game page deadline, which a group barrier's
    ``late_after`` counts from, from the latest the game could end to
    ``ended``, when their game ended, keeping the control's
    ``show_result_for`` on top."""
    from .control import _game_page_deadline

    deadline = _game_page_deadline(session_row.id)
    if deadline is None or ended is None:
        return
    ended = min(deadline, ended)
    for participant in players:
        for link in participant.sync_group_links:
            # Only the game page sets a deadline this late: the PlayLiveGame's
            # barrier clears the previous one, and the game page sets its own
            # to the latest end, plus show_result_for. A deadline before the
            # latest end belongs to another page, so it stays as it is.
            if (
                link.active
                and link.page_deadline is not None
                and link.page_deadline >= deadline
            ):
                link.page_deadline = ended + (link.page_deadline - deadline)


def _record_outcome_on_round(session_row):
    from ..sync import SyncGroupRound

    SyncGroupRound.query.filter_by(live_game_id=session_row.id).update(
        {"live_game_outcome": session_row.outcome}, synchronize_session="fetch"
    )
