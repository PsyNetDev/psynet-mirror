"""The test experiment for live sessions, in which pairs play a session of a
toy game."""

import pytest
from dallinger import db
from dallinger.models import RealtimeSession
from dominate import tags

import psynet.experiment
from psynet.live_session import (
    LiveMessage,
    LiveSession,
    LiveSessionControl,
    LiveSessionInitializer,
    live_session_id,
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Response, Timeline


class Pick(LiveMessage):
    type = "pick"
    number: int

    def apply(self, game, state, player_id, now):
        state["picks"][player_id] = self.number
        game.queue_bonus(player_id, state["pick_bonus"])


class PickNumbers(LiveSession):
    """Each player picks a whole number, and the game ends once both have."""

    channel = "pick_numbers"
    messages = [Pick]
    # So that a session that stalls fails psynet test within a minute.
    max_duration = 60

    def initial_state(self, players, settings=None):
        return {
            "picks": {player: None for player in players},
            # The initializer's settings say what a pick pays.
            "pick_bonus": settings["pick_bonus"] if settings else 0,
        }

    def view(self, state, player_id):
        return {"picked": state["picks"][player_id] is not None}

    def is_over(self, state):
        return all(pick is not None for pick in state["picks"].values())

    def outcome(self, state, reason):
        return state["picks"]

    def bonus(self, outcome, reason, player_id):
        pick = outcome[player_id]
        return 0 if pick is None else pick / 100

    def bot(self, view, player_id, now):
        # Its own id, so the outcome shows which bot picked what.
        return None if view["picked"] else Pick(number=int(player_id))


class Exp(psynet.experiment.Experiment):
    label = "Live session test experiment"
    test_n_bots = 2
    test_mode = "parallel"

    timeline = Timeline(
        InfoPage("The first page.", time_estimate=5),
        SimpleGrouper(
            group_type="pair",
            initial_group_size=2,
            # A participant whose partner leaves the pair goes on without it.
            below_quorum="continue_without_group",
        ),
        # A participant who stays on this page keeps their partner waiting at
        # the initializer.
        InfoPage("You have a partner.", time_estimate=5),
        LiveSessionInitializer(
            id_="pick_numbers",
            group_type="pair",
            game_type=PickNumbers,
            settings={"pick_bonus": 0.5},
            # A participant whose partner doesn't arrive goes on without a
            # session.
            max_wait_time=15,
            max_wait_action="leave_group",
        ),
        ModularPage(
            "pick_numbers",
            Prompt(
                tags.div(
                    tags.p("Joining...", id="game-status"),
                    tags.input_(type="number", id="pick-number", value="7"),
                    tags.button("Pick", type="button", id="pick"),
                    tags.p(id="game-error"),
                )
            ),
            LiveSessionControl("pick_numbers"),
            js_page_modules=["/static/pick-numbers.js"],
            time_estimate=5,
        ),
        InfoPage("The page after the game.", time_estimate=5),
    )

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        session_id = live_session_id(bot, "pick_numbers")
        session = (
            db.session.query(
                RealtimeSession.status,
                RealtimeSession.error,
                RealtimeSession.members,
                RealtimeSession.bots,
                RealtimeSession.end_reason,
                RealtimeSession.outcome,
            )
            .filter_by(id=session_id)
            .one()
        )
        assert session.status == "ended", session.error
        assert sorted(session.bots) == sorted(session.members)
        assert session.end_reason == "finished"
        assert session.outcome == {str(member): member for member in session.members}
        (answer,) = (
            db.session.query(Response.answer)
            .filter_by(
                participant_id=bot.id,
                question="pick_numbers",
                successful_validation=True,
            )
            .one()
        )
        assert answer == session.outcome
        # 0.5 from Pick's queue_bonus, as the initializer's settings say, plus the bot's pick (its id) / 100
        # from bonus.
        assert bot.performance_reward == pytest.approx(0.5 + bot.id / 100)
