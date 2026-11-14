"""What PsyNet does with a live session's record as Dallinger writes it: the
rewards from add_performance_reward, paid by effects queued during the game,
and, once the ending is saved, the rewards from the outcome and the copy of
the outcome on the session's round. All run in the job that writes the session's record, so each
runs once, whether or not the players are still on the game page."""

import functools

from dallinger import db
from dallinger.realtime.utils import is_number

# The name of the effect add_performance_reward queues.
_REWARD_EFFECT = "psynet_performance_reward"


def _check_reward(amount, what):
    if not is_number(amount) or amount < 0:
        raise ValueError(
            f"{what} gave the reward {amount!r}. A reward must be a number of 0 or more."
        )
    # A NumPy number, for example, can't go into JSON or Postgres as it is.
    return float(amount)


def _add_reward(participant, amount):
    if amount:
        participant.inc_performance_reward(amount)


def _locked_players(session_row):
    """Return the session's players, locked so a reward isn't lost to a
    request changing a participant at the same time. They are locked in id
    order, so a job paying several of them can't deadlock with another
    transaction locking them in a different order."""
    from ..participant import Participant

    return (
        db.session.query(Participant)
        .filter(Participant.id.in_(session_row.members))
        .order_by(Participant.id)
        .with_for_update(of=Participant)
        .populate_existing()
        .all()
    )


def _handles_reward(method):
    @functools.wraps(method)
    def handle_effect(self, name, payload, session_row):
        if name != _REWARD_EFFECT:
            return method(self, name, payload, session_row)
        player_id = payload["player_id"]
        if player_id not in {str(member) for member in session_row.members}:
            raise ValueError(
                f"{type(self).__name__}.add_performance_reward gave a reward to "
                f"{player_id!r}, who isn't a player in session {session_row.id}."
            )
        players = _locked_players(session_row)
        (participant,) = [p for p in players if p.id == int(player_id)]
        _add_reward(participant, payload["amount"])

    handle_effect._psynet_wrapper = True
    return handle_effect


def _handles_ending(method):
    @functools.wraps(method)
    def handle_ending(self, session_row):
        # A failed session has no outcome if Dallinger couldn't get one from
        # the game's outcome method.
        players = _locked_players(session_row)
        if session_row.status != "failed" or session_row.outcome is not None:
            _pay_outcome_rewards(self, session_row, players)
            _record_outcome_on_round(session_row)
        _end_game_page_deadlines(session_row, players)
        return method(self, session_row)

    handle_ending._psynet_wrapper = True
    return handle_ending


def _pay_outcome_rewards(game, session_row, players):
    what = f"{type(game).__name__}.performance_reward"
    for participant in players:
        amount = game.performance_reward(
            session_row.outcome, session_row.end_reason, str(participant.id)
        )
        _add_reward(participant, _check_reward(amount, what))


def _end_game_page_deadlines(session_row, players):
    """Move the players' game page deadline, which a group barrier's
    ``late_after`` counts from, from the latest the session could end to when
    it ended, keeping the control's ``show_result_for`` on top."""
    from .control import _game_page_deadline

    deadline = _game_page_deadline(session_row.id)
    if deadline is None or session_row.end_time is None:
        return
    ended = min(deadline, session_row.end_time)
    for participant in players:
        for link in participant.sync_group_links:
            # The PlayLiveGame's barrier cleared the deadline, so one at or after the
            # latest end was set by the game page.
            if (
                link.active
                and link.page_deadline is not None
                and link.page_deadline >= deadline
            ):
                link.page_deadline = ended + (link.page_deadline - deadline)


def _record_outcome_on_round(session_row):
    from ..sync import SyncGroupRound

    SyncGroupRound.query.filter_by(live_session_id=session_row.id).update(
        {"live_session_outcome": session_row.outcome}, synchronize_session="fetch"
    )
