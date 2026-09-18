from __future__ import annotations

import math
import random
from copy import deepcopy
from datetime import datetime
from typing import ClassVar

from dominate import tags
from pydantic import Field
from sqlalchemy import Column

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.consent import NoConsent
from psynet.field import PythonDict, PythonList
from psynet.modular_page import ModularPage
from psynet.page import InfoPage, WaitPage
from psynet.participant import Participant
from psynet.session import (
    LiveSession,
    LiveSessionControl,
    LiveSessionInitializer,
    session,
)
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.websocket import ClientWebSocketMessage, ServerWebSocketMessage

GROUP_TYPE = "shared_canvas_group"
GROUP_SIZE = 2
CANVAS_SIZE = 640
TRIAL_SECONDS = 35
SEND_INTERVAL_MS = 50
DRAW_INTERVAL_MS = 25
PLAYER_RADIUS = 12
COIN_RADIUS = 10
COIN_BONUS = 0.10
COINS_PER_WORLD = 8
N_WORLDS = 3
POSITION_EVENT = "position"
COLLECT_EVENT = "collect"

PLAYER_COLORS = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#9467bd",
    "#ff7f0e",
    "#17becf",
]


def clamp(value, low, high):
    return max(low, min(high, value))


def generate_world(world_index: int) -> dict:
    seed = 20260706 + world_index * 101
    rng = random.Random(seed)
    margin = 60
    coins = []
    for coin_index in range(COINS_PER_WORLD):
        coins.append(
            {
                "id": f"world-{world_index}-coin-{coin_index + 1}",
                "x": round(rng.uniform(margin, CANVAS_SIZE - margin), 1),
                "y": round(rng.uniform(margin, CANVAS_SIZE - margin), 1),
                "radius": COIN_RADIUS,
            }
        )
    return {
        "world_id": f"world-{world_index}",
        "seed": seed,
        "canvas_size": CANVAS_SIZE,
        "player_radius": PLAYER_RADIUS,
        "coin_radius": COIN_RADIUS,
        "coin_bonus": COIN_BONUS,
        "coins": coins,
    }


WORLD_DEFINITIONS = [generate_world(i + 1) for i in range(N_WORLDS)]


def receive_time_iso(receive_time: datetime):
    return receive_time.isoformat()


def initial_canvas_players(participant_ids: list[int], canvas_size: int) -> dict:
    """Return initial participant positions for the shared canvas."""

    ordered_ids = [str(p) for p in participant_ids]
    players = {}
    for index, participant_id in enumerate(ordered_ids):
        angle = (2 * math.pi * index) / max(1, len(ordered_ids))
        players[participant_id] = {
            "participant_id": participant_id,
            "label": f"Player {index + 1}",
            "color": PLAYER_COLORS[index % len(PLAYER_COLORS)],
            "x": round(canvas_size / 2 + math.cos(angle) * 70, 2),
            "y": round(canvas_size / 2 + math.sin(angle) * 70, 2),
            "vx": 0,
            "vy": 0,
            "client_time": 0,
            "receive_time": None,
        }
    return players


class PositionMessage(ClientWebSocketMessage):
    """High-frequency player position payload."""

    event_type: ClassVar[str] = POSITION_EVENT
    x: float = Field(ge=0, le=CANVAS_SIZE)
    y: float = Field(ge=0, le=CANVAS_SIZE)
    vx: float
    vy: float
    client_time: float

    @session()
    def handle(
        self,
        experiment,
        participant,
        session: SharedCanvasSession,
        receive_time,
    ):
        """Broadcast this high-frequency position event."""

        PositionUpdateMessage(
            participant_id=str(participant.id),
            x=round(clamp(self.x, 0, CANVAS_SIZE), 3),
            y=round(clamp(self.y, 0, CANVAS_SIZE), 3),
            vx=round(self.vx, 3),
            vy=round(self.vy, 3),
            client_time=self.client_time,
            receive_time=receive_time_iso(receive_time),
        ).send(
            session.participants,
        )


class CollectMessage(ClientWebSocketMessage):
    """Coin collection attempt payload."""

    event_type: ClassVar[str] = COLLECT_EVENT
    coin_id: str = Field(min_length=1)
    x: float = Field(ge=0, le=CANVAS_SIZE)
    y: float = Field(ge=0, le=CANVAS_SIZE)
    client_time: float

    @session(mutate=True, logging=True)
    def handle(
        self,
        experiment,
        participant,
        session: SharedCanvasSession,
        receive_time,
    ):
        """Apply this coin collection attempt to authoritative state."""

        accepted, reason, collection = session.record_collection(
            participant_id=participant.id,
            coin_id=self.coin_id,
            x=self.x,
            y=self.y,
            receive_time=receive_time,
        )
        if accepted:
            participant.current_trial.record_coin()
            CoinCollectedMessage(
                coin_id=collection["coin_id"],
                participant_id=collection["participant_id"],
                x=collection["x"],
                y=collection["y"],
                bonus=collection["bonus"],
                receive_time=collection["receive_time"],
                coins=session.coins or [],
            ).send(
                session.participants,
            )
        else:
            CollectRejectedMessage(
                coin_id=self.coin_id,
                reason=reason,
            ).send(
                participant,
            )


class PositionUpdateMessage(ServerWebSocketMessage):
    """Broadcast player position update."""

    event_type: ClassVar[str] = "position_update"
    save: ClassVar[bool] = False
    participant_id: str
    x: float
    y: float
    vx: float
    vy: float
    client_time: float
    receive_time: str


class CoinCollectedMessage(ServerWebSocketMessage):
    """Broadcast an accepted coin collection."""

    event_type: ClassVar[str] = "coin_collected"
    coin_id: str
    participant_id: str
    x: float
    y: float
    bonus: float
    receive_time: str
    coins: list[dict]


class CollectRejectedMessage(ServerWebSocketMessage):
    """Notify a participant that a collection attempt was rejected."""

    event_type: ClassVar[str] = "collect_rejected"
    coin_id: str
    reason: str


def instruction_page():
    content = tags.div()
    with content:
        tags.h2("Shared canvas navigation")
        tags.p(
            "You will enter a square canvas with other live participants. "
            "Use the arrow keys to move your avatar."
        )
        tags.p(
            "Your movement has a little inertia: when you release a key, your "
            "avatar slows down smoothly instead of stopping immediately."
        )
        tags.p(
            "Coins are visible to everyone. Move over a coin to collect it. "
            "Each coin you collect adds $0.10 to your bonus."
        )
    return InfoPage(content, time_estimate=20)


class SharedCanvasSession(LiveSession):
    """Persisted live session for one shared-canvas group."""

    players = Column(PythonDict, default=lambda: {})
    coins = Column(PythonList, default=lambda: [])
    collected_coins = Column(PythonList, default=lambda: [])

    def initialize(self, participant_ids, group):
        """Initialize the authoritative shared-canvas state."""

        world = self.node.definition["world"]
        self.players = initial_canvas_players(participant_ids, world["canvas_size"])
        self.coins = deepcopy(world["coins"])
        self.collected_coins = []

    def record_collection(
        self,
        *,
        participant_id: int,
        coin_id: str,
        x: float,
        y: float,
        receive_time,
    ):
        """Apply a validated collection attempt to authoritative state."""

        participant_id = str(participant_id)
        coins = self.coins or []
        coin = next((c for c in coins if c["id"] == coin_id), None)
        if coin is None:
            return False, "already_collected_or_unknown", None

        player = (self.players or {}).get(participant_id)
        if player is None:
            return False, "unknown_player", None

        distance = math.hypot(float(coin["x"]) - x, float(coin["y"]) - y)
        collect_radius = float(coin.get("radius", COIN_RADIUS)) + PLAYER_RADIUS + 4
        if distance > collect_radius:
            return False, "too_far", None

        self.coins = [c for c in coins if c["id"] != coin_id]
        collected = {
            "coin_id": coin_id,
            "participant_id": participant_id,
            "x": coin["x"],
            "y": coin["y"],
            "bonus": COIN_BONUS,
            "receive_time": receive_time_iso(receive_time),
        }
        self.collected_coins = [*(self.collected_coins or []), collected]
        return True, None, collected


class SharedCanvasControl(LiveSessionControl):
    """Custom canvas renderer wrapped in PsyNet's modular page API."""

    external_template = "shared_canvas.html"
    macro = "shared_canvas_control"

    def __init__(self, participant):
        super().__init__(
            participant=participant,
            session_class=SharedCanvasSession,
            group_type=GROUP_TYPE,
            session_initializer_id="shared_canvas_session",
            show_next_button=False,
        )

    def get_css_links(self):
        return ["/static/shared-canvas.css"]

    def get_js_page_modules(self):
        return ["/static/shared-canvas.js"]

    def get_js_vars(self):
        return {"shared_canvas_config": self.canvas_config}

    @property
    def canvas_config(self):
        """Return canvas settings for the browser template."""

        return {
            "canvas_size": CANVAS_SIZE,
            "trial_seconds": TRIAL_SECONDS,
            "send_interval_ms": SEND_INTERVAL_MS,
            "draw_interval_ms": DRAW_INTERVAL_MS,
            "player_radius": PLAYER_RADIUS,
            "coin_radius": COIN_RADIUS,
            "coin_bonus": COIN_BONUS,
        }

    def get_bot_response(self, experiment, bot, page, prompt):
        return {
            "final_position": {"x": 0, "y": 0, "vx": 0, "vy": 0},
            "n_collected_coins": 0,
        }


class SharedCanvasTrial(StaticTrial):
    time_estimate = TRIAL_SECONDS + 35

    @property
    def coin_count(self) -> int:
        """Return the number of accepted coins for this participant's trial."""

        return int((self.vars or {}).get("coins", 0))

    def record_coin(self):
        """Increment the trial coin count after an accepted collection."""

        self.var.coins = self.coin_count + 1

    def show_trial(self, experiment, participant):
        return join(
            instruction_page(),
            LiveSessionInitializer(
                id_="shared_canvas_session",
                group_type=GROUP_TYPE,
                session_class=SharedCanvasSession,
                max_wait_time=90,
            ),
            self.play_canvas(participant),
            GroupBarrier(
                id_="canvas_finished",
                group_type=GROUP_TYPE,
                waiting_logic=WaitPage(wait_time=0.5, save_answer=False),
                max_wait_time=90,
            ),
        )

    def play_canvas(self, participant):
        prompt = tags.div()
        with prompt:
            tags.p(
                "Use the arrow keys to move. Collect the gold coins before the "
                "session ends."
            )
        return ModularPage(
            "shared_canvas",
            prompt,
            SharedCanvasControl(participant),
            time_estimate=TRIAL_SECONDS + 5,
        )

    def score_answer(self, answer, definition):
        return self.coin_count

    def compute_performance_reward(self, score):
        return max(0.0, score * COIN_BONUS)

    def show_feedback(self, experiment, participant):
        bonus = self.compute_performance_reward(self.coin_count)
        content = tags.div()
        with content:
            tags.h2("Navigation complete")
            tags.p(f"Your coin bonus is ${bonus:.2f}.")
            tags.p("Thank you for exploring the shared canvas.")
        return InfoPage(content, time_estimate=5)


class Exp(psynet.experiment.Experiment):
    label = "Real-time shared canvas navigation"
    variables_initial_values = {
        "group_size": GROUP_SIZE,
        "canvas_size": CANVAS_SIZE,
        "trial_seconds": TRIAL_SECONDS,
        "send_interval_ms": SEND_INTERVAL_MS,
        "draw_interval_ms": DRAW_INTERVAL_MS,
        "coin_bonus": COIN_BONUS,
        "soft_max_experiment_payment": 1000.0,
        "hard_max_experiment_payment": 1100.0,
        "max_participant_payment": 25.0,
        "soft_max_experiment_payment_email_sent": False,
        "hard_max_experiment_payment_email_sent": False,
    }

    timeline = Timeline(
        NoConsent(),
        SimpleGrouper(
            group_type=GROUP_TYPE,
            initial_group_size=GROUP_SIZE,
            batch_size=GROUP_SIZE,
            max_wait_time=180,
        ),
        StaticTrialMaker(
            id_="shared_canvas_worlds",
            trial_class=SharedCanvasTrial,
            nodes=[
                StaticNode(definition={"world": world}) for world in WORLD_DEFINITIONS
            ],
            expected_trials_per_participant=1,
            max_trials_per_participant=1,
            sync_group_type=GROUP_TYPE,
            check_performance_at_end=False,
        ),
    )

    test_n_bots = 4
    test_mode = "serial"

    def test_serial_run_bots(self, bots: list[BotDriver]):
        advance_past_wait_pages(bots)

        for bot in bots:
            assert "Shared canvas navigation" in bot.current_page_text
            assert "Each coin you collect adds $0.10" in bot.current_page_text
            bot.take_page()

        advance_past_wait_pages(bots)

        for bot in bots:
            assert bot.current_page_label == "shared_canvas"
            bot.take_page()

        advance_past_wait_pages(bots)

        answers_by_group = {}
        for bot in bots:
            assert "Navigation complete" in bot.current_page_text
            answer = bot.current_trial.answer
            assert isinstance(answer, dict)
            assert answer == {
                "final_position": {"x": 0, "y": 0, "vx": 0, "vy": 0},
                "n_collected_coins": 0,
            }
            assert bot.current_trial.score == 0
            participant = Participant.query.get(bot.id)
            group_id = int(participant.active_sync_groups[GROUP_TYPE].id)
            answers_by_group.setdefault(group_id, []).append(answer)

        assert len(answers_by_group) == len(bots) // GROUP_SIZE
        assert all(
            len(group_answers) == GROUP_SIZE
            for group_answers in answers_by_group.values()
        )
