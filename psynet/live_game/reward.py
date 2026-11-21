"""What PsyNet does with a live game's record as Dallinger writes it: the
rewards from add_performance_reward, paid by effects queued during the game,
the reward from the outcome of a player whose game ends before the game
does, and, once the result is saved, the other players' rewards from the
outcome, the copy of the outcome on the game's round, and the removal of
players who didn't play from their groups, for a PlayLiveGame with
``absent_action``. The group's top-ups stop when the game stops taking
players and, unless the PlayLiveGame says otherwise, when it ends. A
player who came too late gets nothing from the game, which never saw
them. A reward is also recorded on the trial
the game was played in, if any. All run in the job that writes the game's
record, so each runs once, whether or not the players are still on the game
page."""

from dallinger import db
from dallinger.models import timenow
from dallinger.realtime.utils import is_number

from .method_wrappers import _outermost
from .psynet_entry import TOO_LATE
from .record import (
    _CLOSED_EFFECT,
    _PSYNET_EFFECTS,
    _REWARD_EFFECT,
    _game_started_at,
    _game_time,
    _has_outcome,
    _player_ids,
    _players_ended_early,
    _record_from_row,
)


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


@_outermost
def _handles_reward(self, game_code, name, payload, session_row):
    if name not in _PSYNET_EFFECTS:
        return game_code(name, payload, _record_from_row(session_row))
    if name == _CLOSED_EFFECT:
        from .play import _stop_top_ups_soon

        _stop_top_ups_soon(payload["group_id"], session_row.id)
        return None
    if name != _REWARD_EFFECT:
        # Only recorded, for a game record's messages and moments.
        return None
    player = payload["player"]
    participant_ids = _player_ids(session_row.members)
    if player >= len(participant_ids):
        raise ValueError(
            f"{type(self).__name__}.add_performance_reward gave a reward to "
            f"player {player}, but game {session_row.id} has only "
            f"{len(participant_ids)} players, numbered from 0."
        )
    (participant,) = _locked_players(session_row, [participant_ids[player]])
    _add_reward(participant, payload["amount"], session_row)


@_outermost
def _handles_ending(self, game_code, session_row):
    # Players whose own game ended early were paid then, and may be on
    # a later page whose deadline isn't the game's. They aren't locked,
    # as one back at a PlayLiveGame holds their row while waiting for
    # this game's.
    ended_early = _players_ended_early(session_row.id)
    remaining = [
        participant_id
        for participant_id in session_row.members
        if participant_id not in ended_early
    ]
    players = _locked_players(session_row, remaining) if remaining else []
    from .play import _remove_absent_players, _stop_top_ups_soon

    if _has_outcome(session_row.status, session_row.outcome):
        _pay_outcome_rewards(self, session_row, players)
        _record_outcome_on_round(session_row)
    _end_game_page_deadlines(session_row, players, session_row.end_time)
    entry = (session_row.final_state or {}).get("psynet")
    if entry is not None and entry["stop_top_ups_at_end"]:
        _stop_top_ups_soon(entry["group_id"], session_row.id)
    if session_row.status != "failed":
        _remove_absent_players(self, session_row, players)
    return game_code(_record_from_row(session_row))


@_outermost
def _handles_player_ending(self, game_code, session_row, player_id, ending):
    (participant,) = _locked_players(session_row, [int(player_id)])
    if ending["reason"] == TOO_LATE:
        # The game never saw them, so it has nothing to pay or handle.
        _end_game_page_deadlines(session_row, [participant], timenow())
        return None
    player = _player_ids(session_row.members).index(participant.id)
    amount = self.performance_reward(ending["outcome"], ending["reason"], player)
    what = f"{type(self).__name__}.performance_reward"
    _add_reward(participant, _check_reward(amount, what), session_row)
    _end_game_page_deadlines(session_row, [participant], timenow())
    ending = {
        **ending,
        "time": _game_time(_game_started_at(session_row.id), ending["time"]),
    }
    return game_code(_record_from_row(session_row), player, ending)


def _pay_outcome_rewards(game, session_row, players):
    what = f"{type(game).__name__}.performance_reward"
    participant_ids = _player_ids(session_row.members)
    for participant in players:
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
