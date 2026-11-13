"""A live session's rewards: those from the outcome, paid when each player's
answer is accepted, and those from add_performance_reward, paid by effects queued during
the game."""

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


def _handles_reward(method):
    @functools.wraps(method)
    def handle_effect(self, name, payload, session_row):
        if name != _REWARD_EFFECT:
            return method(self, name, payload, session_row)
        from ..participant import Participant

        player_id = payload["player_id"]
        if player_id not in {str(member) for member in session_row.members}:
            raise ValueError(
                f"{type(self).__name__}.add_performance_reward gave a reward to "
                f"{player_id!r}, who isn't a player in session {session_row.id}."
            )
        # Locked, so the reward isn't lost to a request changing the
        # participant at the same time. Every player is locked, in id order,
        # so a job handling rewards for several of them can't deadlock with
        # another transaction locking them in a different order.
        players = (
            db.session.query(Participant)
            .filter(Participant.id.in_(session_row.members))
            .order_by(Participant.id)
            .with_for_update(of=Participant)
            .populate_existing()
            .all()
        )
        (participant,) = [p for p in players if p.id == int(player_id)]
        _add_reward(participant, payload["amount"])

    handle_effect._psynet_wrapper = True
    return handle_effect
