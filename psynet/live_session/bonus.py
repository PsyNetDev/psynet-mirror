"""A live session's bonuses: those from the outcome, paid when each player's
answer is accepted, and those from queue_bonus, paid by effects queued during
the game."""

import functools

from dallinger import db
from dallinger.realtime.utils import is_number

# The name of the effect queue_bonus queues.
_BONUS_EFFECT = "psynet_bonus"


def _check_bonus(amount, what):
    if not is_number(amount) or amount < 0:
        raise ValueError(
            f"{what} gave the bonus {amount!r}. A bonus must be a number of 0 or more."
        )
    # A NumPy number, for example, can't go into JSON or Postgres as it is.
    return float(amount)


def _add_bonus(participant, amount):
    if amount:
        participant.inc_performance_reward(amount)


def _handles_bonus(method):
    @functools.wraps(method)
    def handle_effect(self, name, payload, session_row):
        if name != _BONUS_EFFECT:
            return method(self, name, payload, session_row)
        from ..participant import Participant

        player_id = payload["player_id"]
        if player_id not in {str(member) for member in session_row.members}:
            raise ValueError(
                f"{type(self).__name__}.queue_bonus gave a bonus to "
                f"{player_id!r}, who isn't a player in session {session_row.id}."
            )
        # Locked, so the bonus isn't lost to a request changing the
        # participant at the same time. Every player is locked, in id order,
        # so a job handling bonuses for several of them can't deadlock with
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
        _add_bonus(participant, payload["amount"])

    handle_effect._psynet_wrapper = True
    return handle_effect
