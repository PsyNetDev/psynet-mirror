"""The test experiment for live sessions. Its first page opens the page's
websocket, and then pairs start a session of a toy game."""

from dominate import tags

import psynet.experiment
from psynet.live_session import LiveMessage, LiveSession, LiveSessionInitializer
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Timeline


class Pick(LiveMessage):
    type = "pick"
    number: int

    def apply(self, game, state, player_id, now):
        state["picks"][player_id] = self.number


class PickNumbers(LiveSession):
    """Each player picks a whole number, and the game ends once both have."""

    channel = "pick_numbers"
    messages = [Pick]

    def initial_state(self, players):
        return {"picks": {player: None for player in players}}

    def view(self, state, player_id):
        return {"picked": state["picks"][player_id] is not None}

    def is_over(self, state):
        return all(pick is not None for pick in state["picks"].values())

    def outcome(self, state, reason):
        return state["picks"]


class Exp(psynet.experiment.Experiment):
    label = "Live session test experiment"
    test_n_bots = 2
    test_mode = "parallel"

    timeline = Timeline(
        InfoPage(
            tags.p("Connecting...", id="socket-status"),
            time_estimate=5,
            js_page_code=(
                "psynet.websocket.onConnect(() => {"
                ' root.querySelector("#socket-status").textContent = "Connected";'
                " });"
            ),
        ),
        InfoPage("The next page.", time_estimate=5),
        SimpleGrouper(group_type="pair", initial_group_size=2),
        LiveSessionInitializer(
            id_="pick_numbers", group_type="pair", game_type=PickNumbers
        ),
        InfoPage("The game page.", time_estimate=5),
    )
