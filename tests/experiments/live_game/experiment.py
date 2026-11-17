"""The test experiment for live games, in which pairs play a game of a
toy game."""

import pytest
from dallinger import db
from dallinger.models import RealtimeSession
from dominate import tags

import psynet.experiment
from psynet.live_game import (
    LiveGame,
    LiveGameControl,
    LiveMessage,
    PlayLiveGame,
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Response, Timeline


class Pick(LiveMessage):
    type = "pick"
    number: int

    def apply(self, game, state, player, now):
        state["picks"][player] = self.number
        game.add_performance_reward(player, state["pick_reward"])


class PickNumbers(LiveGame):
    """Each player picks a whole number, and the game ends once both have."""

    channel = "pick_numbers"
    messages = [Pick]
    # So that a game that stalls fails psynet test within a few minutes.
    timeout = 60

    def initial_state(self, players, settings=None):
        return {
            "picks": [None for player in players],
            # The PlayLiveGame's settings say what a pick pays.
            "pick_reward": settings["pick_reward"] if settings else 0,
        }

    def view(self, state, player):
        return {"picked": state["picks"][player] is not None}

    def is_over(self, state):
        return None not in state["picks"]

    def outcome(self, state, reason):
        return state["picks"]

    def performance_reward(self, outcome, reason, player):
        pick = outcome[player]
        return 0 if pick is None else pick / 100

    def bot(self, view, player, now):
        # 10 more than its number, so the outcome shows which bot picked what.
        return None if view["picked"] else Pick(number=10 + player)


class GrowingPicks(PickNumbers):
    """Pick numbers, which players can join while it runs, and in which
    each player's game ends once they've picked."""

    channel = "growing_picks"
    min_players = 1

    def on_add(self, state, player, now):
        state["picks"].append(None)
        self.record("joined", {"player": player})

    def is_done(self, state, player):
        return state["picks"][player] is not None


class Exp(psynet.experiment.Experiment):
    label = "Live game test experiment"
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
        # the game.
        InfoPage("You have a partner.", time_estimate=5),
        PlayLiveGame(
            group_type="pair",
            game_class=PickNumbers,
            page=ModularPage(
                "pick_numbers",
                Prompt(
                    tags.div(
                        tags.p("Joining...", id="game-status"),
                        tags.input_(type="number", id="pick-number", value="7"),
                        tags.button("Pick", type="button", id="pick"),
                        tags.p(id="game-error"),
                    )
                ),
                LiveGameControl(),
                js_page_modules=["/static/pick-numbers.js"],
                time_estimate=5,
            ),
            settings={"pick_reward": 0.5},
            # A participant whose partner doesn't arrive goes on without a
            # game.
            max_wait_time=15,
            max_wait_action="leave_group",
        ),
        InfoPage("The page after the game.", time_estimate=5),
    )

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        session_id = bot.live_game_ids.get("pick_numbers")
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
        assert session.outcome == [10 + player for player in range(2)]
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
        # 0.5 from Pick's add_performance_reward, as the game's settings say,
        # plus the bot's pick / 100 from performance_reward.
        player = [int(member) for member in session.members].index(bot.id)
        assert bot.performance_reward == pytest.approx(0.5 + (10 + player) / 100)
