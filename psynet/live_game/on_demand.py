"""Deliver a solo trial maker's assignments to one open live-game page."""

from datetime import datetime
from functools import partial

from dallinger import db
from dallinger.models import RealtimeSession
from dallinger.realtime import end_realtime_session
from flask import abort
from pydantic import ValidationError

from .game import LiveGame
from .registry import _live_game_class
from .trials import TrialAnswer


class OnDemandTrialGame(LiveGame):
    """Play native trials from the active maker, selecting one after each answer.

    Set answer_type to a TrialAnswer subclass and implement bot_answer(view).
    The browser uses onTrial and startResponseClock. Trial answers go to a
    participant-locked SQL request. The runner manages presence and game ending.
    """

    min_players = max_players = 1
    answer_type = TrialAnswer

    def initial_state(self, players):
        return {}

    def view(self, state, player):
        return {}

    def bot(self, view, player, now):
        # The runner handles readiness. A bot answers assignments in the same
        # SQL path as a browser when its participant driver visits the page.
        return None

    @staticmethod
    def bot_answer(view):
        raise NotImplementedError

    @staticmethod
    def start(participant, session_id):
        from ..experiment import get_trial_maker
        from ..trial.main import TrialMakerState

        run = participant.module_state
        if not isinstance(run, TrialMakerState):
            raise ValueError("Play an OnDemandTrialGame inside its trial maker.")
        maker = get_trial_maker(run.module_id)
        if maker.sync_group_type or maker.check_performance_every_trial:
            raise ValueError(
                "On-demand trials require independent selection without per-trial performance pages."
            )
        run.var.on_demand_session = session_id
        run.var.on_demand_ending = None
        run.var.on_demand_last_response = None
        run.var.on_demand_wait_started = None
        participant.current_trial = None

    @classmethod
    def step(cls, experiment, participant, session_id, submission=None):
        """Called with the participant locked. A lost reply can be requested again."""
        from ..experiment import get_trial_maker

        run = participant.module_state
        maker = get_trial_maker(run.module_id)
        current = participant.current_trial
        if submission is not None:
            try:
                msg = cls.answer_type.model_validate(
                    submission, strict=True, extra="forbid"
                )
            except ValidationError:
                abort(400, "Invalid trial response.")
            receipt = msg.model_dump(mode="json")
            if receipt != run.var.on_demand_last_response:
                if (
                    current is None
                    or current.complete
                    or current.failed
                    or current.position != msg.position
                ):
                    abort(409, "This trial is no longer open.")
                current.time_taken = msg.seconds
                current._complete_with_answer(msg.answer, experiment, maker)
                db.session.flush()
                run.var.on_demand_last_response = receipt
                current = None

        ending = run.var.on_demand_ending
        if ending is None and current is None:
            current, status = maker._prepare_trial(experiment, participant)
            participant.current_trial = current
            participant.trial_status = status
            if status == "wait":
                now = datetime.now().timestamp()
                started = run.var.on_demand_wait_started
                if started is None:
                    run.var.on_demand_wait_started = now
                limit = maker.max_time_waiting_for_trial
                if started is None or limit is None or now - started < limit:
                    return {"status": "wait"}
                ending = "trial_wait_timeout"
            run.var.on_demand_wait_started = None
            if status == "exit":
                ending = "finished"
            if ending:
                run.var.on_demand_ending = ending
            if current is not None:
                current.response_started_at = datetime.now()

        if ending:
            db.run_after_commit(partial(end_realtime_session, session_id, ending))
            return {"status": "finished"}
        return {
            "status": "available",
            "completed": current.position,
            "definition": maker.live_trial_definition(current),
        }


def page_step(experiment, participant, body):
    run = participant.module_state
    session_id = body.get("session")
    if (
        participant.failed
        or participant.status != "working"
        or not participant.page_uuid
        or body.get("page") != participant.page_uuid
        or type(session_id) is not int
        or run is None
        or run.var.get("on_demand_session") != session_id
    ):
        abort(409, "This game page is no longer current.")
    session = db.session.get(RealtimeSession, session_id)
    game = _live_game_class(session.game_type)
    if session.status != "running":
        abort(409, "This game has ended.")
    return game.step(experiment, participant, session_id, body.get("response"))
