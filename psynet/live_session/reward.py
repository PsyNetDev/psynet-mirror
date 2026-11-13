"""A live session's rewards: those from the outcome, paid to every player when
the session's ending is saved, and those from add_performance_reward, paid by
effects queued during the game. Both are paid in the job that writes the
session's record, so each is paid once, whether or not the player is still on
the game page."""

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


def _pays_outcome_rewards(method):
    @functools.wraps(method)
    def handle_ending(self, session_row):
        # A failed session has no outcome if Dallinger couldn't get one from
        # the game's outcome method.
        if session_row.status != "failed" or session_row.outcome is not None:
            what = f"{type(self).__name__}.performance_reward"
            for participant in _locked_players(session_row):
                amount = self.performance_reward(
                    session_row.outcome, session_row.end_reason, str(participant.id)
                )
                _add_reward(participant, _check_reward(amount, what))
        return method(self, session_row)

    handle_ending._psynet_wrapper = True
    return handle_ending
