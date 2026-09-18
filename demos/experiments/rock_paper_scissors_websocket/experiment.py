"""WebSocket rock-paper-scissors demo.

A minimal real-time rock-paper-scissors experiment. Participants are grouped
into pairs with a :class:`~psynet.sync.SimpleGrouper` and a synchronised trial
maker, then they play five rounds of rock-paper-scissors against each other
inside a single trial. Each round's outcome is revealed to both players the
instant they have both chosen, and a running score is displayed throughout.

The participant-facing interface mirrors ``demos/experiments/rock_paper_scissors``
(a coloured "choose your action" prompt with rock/paper/scissors push buttons),
but the round-by-round coordination is driven entirely over WebSockets rather
than by a page reload per round. The design follows PsyNet's built-in WebSocket
and live-session machinery:

* The experiment defines a ``ChooseMessage`` client WebSocket message whose
  ``handle`` method receives every browser choice. Once both players have
  submitted a move for the current round it scores the round and updates the
  persisted :class:`~psynet.session.LiveSession` state.
* :class:`RockPaperScissorsControl` is a :class:`~psynet.session.LiveSessionControl`
  backed by a markup-only custom template, page CSS, and a page module that
  uses ``psynet.websocket`` and ``psynet.session`` for real-time communication
  and refresh/reconnect recovery.

The server is the sole authority for the game state; the browser only sends the
chosen action and drops the server's snapshot text into the page, so there is
almost no game logic in JavaScript. Recoverable game state, including hidden
current-round choices, is persisted in the live-session row. The final score is
recomputed from participant submissions inside a :class:`~psynet.sync.GroupBarrier`
on release, so the flow is also fully testable with non-WebSocket bots.
"""

import random
from copy import deepcopy
from types import SimpleNamespace
from typing import ClassVar, Literal

from dominate import tags
from pydantic import Field, ValidationError
from sqlalchemy import Boolean, Column, Integer

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.field import PythonDict
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

GROUP_TYPE = "rock_paper_scissors"
CHOICES = ["rock", "paper", "scissors"]
N_ROUNDS = 5

# ``SCORING_MATRIX[a][b]`` is the score (win = +1, draw = 0, loss = -1) for a
# player who plays ``a`` against an opponent who plays ``b``. The matrix is
# antisymmetric: ``SCORING_MATRIX[a][b] == -SCORING_MATRIX[b][a]``.
SCORING_MATRIX = {
    "rock": {"rock": 0, "paper": -1, "scissors": 1},
    "paper": {"rock": 1, "paper": 0, "scissors": -1},
    "scissors": {"rock": -1, "paper": 1, "scissors": 0},
}


def score_round(action_self, action_other):
    return SCORING_MATRIX[action_self][action_other]


def score_match(player_1_moves, player_2_moves):
    """Return total scores for two equal-length move sequences."""
    if len(player_1_moves) != len(player_2_moves):
        raise ValueError("Move sequences must have the same length.")

    player_1_score = 0
    player_2_score = 0
    for player_1_move, player_2_move in zip(player_1_moves, player_2_moves):
        score = score_round(player_1_move, player_2_move)
        player_1_score += score
        player_2_score -= score
    return player_1_score, player_2_score


Choice = Literal["rock", "paper", "scissors"]


class ChooseMessage(ClientWebSocketMessage):
    """A participant's committed choice for one websocket game round."""

    event_type: ClassVar[str] = "choose"
    round: int = Field(ge=1, le=N_ROUNDS)
    action: Choice

    @session(mutate=True, logging=True)
    def handle(
        self,
        experiment,
        participant,
        session: "RockPaperScissorsSession",
        receive_time,
    ):
        """Handle this browser-submitted rock-paper-scissors choice."""

        reveals = session.record_choice(participant.id, self)
        if reveals is None:
            return

        participants_by_id = {int(p.id): p for p in session.participants}
        for participant_id, reveal in reveals:
            recipient = participants_by_id.get(int(participant_id))
            if recipient is not None:
                reveal.send(recipient)


class RevealMessage(ServerWebSocketMessage):
    """A participant-specific reveal for a completed round."""

    event_type: ClassVar[str] = "roundReveal"
    target: str
    round: int
    result: str
    scoreboard: str
    status: str
    finished: bool
    answer: list[str] | None = None


class RockPaperScissorsSession(LiveSession):
    """Persisted live session for one rock-paper-scissors game."""

    current_round = Column(Integer)
    scores = Column(PythonDict, default=lambda: {})
    current_round_choices = Column(PythonDict, default=lambda: {})
    submitted_moves = Column(PythonDict, default=lambda: {})
    reveal_history = Column(PythonDict, default=lambda: {})
    finished = Column(Boolean, default=False)

    def initialize(self, participant_ids, group):
        """Initialize the recoverable state for a new RPS session."""

        ordered_ids = [
            str(participant_id) for participant_id in sorted(participant_ids)
        ]
        self.current_round = 1
        self.scores = {participant_id: 0 for participant_id in ordered_ids}
        self.current_round_choices = {}
        self.submitted_moves = {participant_id: [] for participant_id in ordered_ids}
        self.reveal_history = {participant_id: [] for participant_id in ordered_ids}
        self.finished = False

    def snapshot_state(self, fields=None, participant=None):
        """Return reconnect state without leaking hidden participant data."""

        state = super().snapshot_state(fields=None, participant=participant)
        state["submitted_participant_ids"] = sorted(
            str(pid) for pid in (self.current_round_choices or {})
        )
        state.pop("current_round_choices", None)
        state.pop("submitted_moves", None)
        if participant is None:
            state.pop("reveal_history", None)
        else:
            state["reveal_history"] = (self.reveal_history or {}).get(
                str(participant.id), []
            )
        if fields is not None:
            state = {field: state[field] for field in fields if field in state}
        return state

    def record_choice(self, participant_id: int, message: ChooseMessage):
        """Record a choice and return reveals if this completed a round."""

        participant_id = int(participant_id)
        current_round = int(self.current_round or 1)
        expected_ids = [int(value) for value in (self.participant_ids or [])]
        round_moves = {
            int(pid): action
            for pid, action in (self.current_round_choices or {}).items()
        }

        if bool(self.finished):
            return None
        if message.round != current_round:
            return None
        if participant_id not in expected_ids:
            return None
        if participant_id in round_moves:
            return None

        round_moves[participant_id] = message.action
        self.current_round_choices = {
            str(pid): action for pid, action in sorted(round_moves.items())
        }

        reveals = []

        if len(round_moves) >= len(expected_ids):
            pids = sorted(round_moves.keys())
            score_1, score_2 = score_match(
                [round_moves[pids[0]]], [round_moves[pids[1]]]
            )
            scores = dict(self.scores or {})
            scores.setdefault(str(pids[0]), 0)
            scores.setdefault(str(pids[1]), 0)
            scores[str(pids[0])] += score_1
            scores[str(pids[1])] += score_2
            finished = message.round >= N_ROUNDS
            submitted_moves = deepcopy(self.submitted_moves or {})
            for pid in pids:
                pid_key = str(pid)
                submitted_moves.setdefault(pid_key, [])
                submitted_moves[pid_key] = [
                    *submitted_moves[pid_key],
                    round_moves[pid],
                ]
            self.scores = scores
            self.finished = finished
            self.submitted_moves = submitted_moves
            self.current_round_choices = {}
            if not finished:
                self.current_round = message.round + 1

            reveal_history = deepcopy(self.reveal_history or {})
            for pid in pids:
                pid_key = str(pid)
                reveal_history.setdefault(pid_key, [])
                reveal = reveal_for(
                    participant_id=pid,
                    round_number=message.round,
                    round_moves=round_moves,
                    scores=scores,
                    finished=finished,
                    submitted_moves=submitted_moves[pid_key] if finished else None,
                )
                reveals.append((pid, reveal))
                reveal_history[pid_key] = [
                    *reveal_history[pid_key],
                    reveal.model_dump(mode="json", exclude_none=True),
                ]
            self.reveal_history = reveal_history

        return reveals


def reveal_for(
    participant_id: int,
    round_number: int,
    *,
    round_moves: dict[int, Choice],
    scores: dict[str, int],
    finished: bool,
    submitted_moves: list[Choice] | None = None,
) -> RevealMessage:
    """Return a participant-specific reveal for a completed round."""

    partner_id = next(pid for pid in round_moves if pid != participant_id)
    delta = score_round(round_moves[participant_id], round_moves[partner_id])
    outcome = (
        "you won the round!"
        if delta > 0
        else "you lost the round."
        if delta < 0
        else "the round was a draw."
    )
    participant_key = str(participant_id)
    partner_key = str(partner_id)
    return RevealMessage(
        target=participant_key,
        round=round_number + 1,
        result=(
            f"Round {round_number}: you played {round_moves[participant_id]}, "
            f"your partner played {round_moves[partner_id]} — {outcome}"
        ),
        scoreboard=(
            f"Score — you: {scores.get(participant_key, 0)}, "
            f"partner: {scores.get(partner_key, 0)}"
        ),
        status=(
            "Game over!"
            if finished
            else f"Round {round_number + 1} of {N_ROUNDS}: choose your action."
        ),
        finished=finished,
        answer=submitted_moves,
    )


class RockPaperScissorsControl(LiveSessionControl):
    """Control that renders the rock-paper-scissors board and drives it over a
    WebSocket. The submitted answer is the participant's list of ``n_rounds``
    moves."""

    external_template = "rps-control.html"
    macro = "rps_control"

    def __init__(self, participant, color, n_rounds=N_ROUNDS, choices=CHOICES):
        # The board advances itself once all rounds are revealed, so we hide the
        # default 'Next' button and submit programmatically from the page module.
        self.color = color
        self.n_rounds = n_rounds
        self.choices = choices
        super().__init__(
            participant=participant,
            session_class=RockPaperScissorsSession,
            group_type=GROUP_TYPE,
            session_initializer_id="rps_session",
            show_next_button=False,
        )

    def get_css_links(self):
        return ["/static/rps-control.css"]

    def get_js_page_modules(self):
        return ["/static/rps-control.js"]

    def get_js_vars(self):
        return {"rps_config": {"n_rounds": self.n_rounds}}

    def get_bot_response(self, experiment, bot, page, prompt):
        # Bots cannot use WebSockets, so they simply submit a full set of moves;
        # the authoritative scoring happens server-side in ``score_game``.
        return [random.choice(self.choices) for _ in range(self.n_rounds)]


class RockPaperScissorsTrial(StaticTrial):
    time_estimate = 30

    def show_trial(self, experiment, participant):
        return join(
            LiveSessionInitializer(
                id_="rps_session",
                group_type=GROUP_TYPE,
                session_class=RockPaperScissorsSession,
                max_wait_time=120,
            ),
            self.play_game(participant=participant, color=self.definition["color"]),
            GroupBarrier(
                id_="game_finished",
                group_type=GROUP_TYPE,
                waiting_logic=WaitPage(wait_time=0.5, save_answer=False),
                on_release=self.score_game,
                max_wait_time=120,
            ),
        )

    def play_game(self, participant, color):
        prompt = tags.div()
        with prompt:
            tags.h1("Rock, paper, scissors!")
            tags.p(
                f"Play {N_ROUNDS} rounds against your partner. "
                "Each round is revealed as soon as you have both chosen.",
                style=f"color: {color};",
            )
        return ModularPage(
            "play_game",
            prompt,
            RockPaperScissorsControl(participant=participant, color=color),
            time_estimate=30,
            save_answer="rps_moves",
        )

    def score_game(self, participants: list[Participant]):
        assert len(participants) == 2
        sorted_participants = sorted(participants, key=lambda p: p.id)
        moves = [participant.var.rps_moves for participant in sorted_participants]
        totals = score_match(moves[0], moves[1])

        for i, participant in enumerate(sorted_participants):
            j = 1 - i
            participant.var.game_result = {
                "my_moves": moves[i],
                "partner_moves": moves[j],
                "my_score": totals[i],
                "partner_score": totals[j],
                "outcome": (
                    "won"
                    if totals[i] > totals[j]
                    else "lost"
                    if totals[i] < totals[j]
                    else "drew"
                ),
            }

    def show_feedback(self, experiment, participant):
        result = participant.var.game_result
        outcome = {
            "won": "You won the match!",
            "lost": "You lost the match.",
            "drew": "The match was a draw.",
        }[result["outcome"]]

        prompt = tags.div()
        with prompt:
            tags.h1("Game over!")
            tags.p(
                f"Final score — you: {result['my_score']}, "
                f"partner: {result['partner_score']}. {outcome}"
            )
            with tags.ol():
                for me, partner in zip(result["my_moves"], result["partner_moves"]):
                    tags.li(f"You played {me}, your partner played {partner}.")

        return InfoPage(prompt, time_estimate=5)


class Exp(psynet.experiment.Experiment):
    label = "Rock paper scissors WebSocket demo"

    timeline = Timeline(
        SimpleGrouper(
            group_type=GROUP_TYPE,
            initial_group_size=2,
            # Allow ample time for a second participant to arrive in the lobby.
            max_wait_time=300,
        ),
        StaticTrialMaker(
            id_="rock_paper_scissors_websocket",
            trial_class=RockPaperScissorsTrial,
            nodes=[
                StaticNode(definition={"color": color})
                for color in ["red", "green", "blue"]
            ],
            expected_trials_per_participant=1,
            max_trials_per_participant=1,
            sync_group_type=GROUP_TYPE,
        ),
        InfoPage("That's the end of the experiment!", time_estimate=5),
    )

    test_n_bots = 2
    test_mode = "serial"

    @staticmethod
    def _valid_choose_event():
        return ChooseMessage.model_validate(
            {
                "session_id": 1,
                "round": 2,
                "action": "paper",
            }
        )

    @staticmethod
    def _assert_payload_rejected(payload):
        try:
            ChooseMessage.model_validate(payload)
        except (ValidationError, ValueError):
            pass
        else:
            raise AssertionError(f"Expected payload to be rejected: {payload}")

    @staticmethod
    def test_websocket_event_parsing():
        """Check websocket event parsing and validation."""
        session_id = 1
        event = Exp._valid_choose_event()
        assert event == ChooseMessage(
            session_id=session_id,
            round=2,
            action="paper",
        )

        invalid_payloads = [
            {
                "session_id": session_id,
                "round": 1,
                "action": "rock",
                "extra": "unexpected",
            },
            {
                "session_id": "",
                "round": 1,
                "action": "rock",
            },
            {
                "session_id": session_id,
                "round": "1",
                "action": "rock",
            },
            {
                "session_id": session_id,
                "round": 0,
                "action": "rock",
            },
            {
                "session_id": session_id,
                "round": 1,
                "action": "lizard",
            },
        ]
        for payload in invalid_payloads:
            Exp._assert_payload_rejected(payload)

    @staticmethod
    def test_scoring_helpers():
        """Check shared scoring helpers."""
        assert score_match(["rock", "paper"], ["scissors", "rock"]) == (2, -2)

        try:
            score_match(["rock"], ["scissors", "paper"])
        except ValueError:
            pass
        else:
            raise AssertionError("Expected unequal move sequences to be rejected.")

    @staticmethod
    def test_live_session_initialization():
        """Check the recoverable live-session shape."""
        session = RockPaperScissorsSession()
        session.initialize([2, 1], group=None)

        assert session.current_round == 1
        assert session.scores == {"1": 0, "2": 0}
        assert session.current_round_choices == {}
        assert session.submitted_moves == {"1": [], "2": []}
        assert session.reveal_history == {"1": [], "2": []}
        assert session.finished is False

    @staticmethod
    def test_live_session_snapshot_filtering():
        """Check public snapshots and participant-specific reconnect history."""
        session = RockPaperScissorsSession()
        session.initialize([1, 2], group=None)
        session.current_round_choices = {"1": "rock"}
        session.submitted_moves = {"1": ["rock"], "2": ["scissors"]}
        session.reveal_history = {
            "1": [{"target": "1", "result": "you won"}],
            "2": [{"target": "2", "result": "you lost"}],
        }

        snapshot = session.snapshot_state()
        participant_state = session.snapshot_state(participant=SimpleNamespace(id=2))

        assert "current_round_choices" not in snapshot
        assert "submitted_moves" not in snapshot
        assert "reveal_history" not in snapshot
        assert snapshot["submitted_participant_ids"] == ["1"]
        assert participant_state["reveal_history"] == [
            {"target": "2", "result": "you lost"}
        ]

    @staticmethod
    def test_reveal_formatting():
        """Check reveal formatting from public and hidden live-session state."""
        reveal = reveal_for(
            participant_id=1,
            round_number=1,
            round_moves={1: "rock", 2: "scissors"},
            scores={"1": 1, "2": -1},
            finished=False,
        )

        assert reveal.scoreboard == "Score — you: 1, partner: -1"
        assert reveal.finished is False

    def test_websocket_event_contracts(self):
        """Check websocket event, authorization, state, and reveal contracts."""
        self.test_websocket_event_parsing()
        self.test_scoring_helpers()
        self.test_live_session_initialization()
        self.test_live_session_snapshot_filtering()
        self.test_reveal_formatting()

    def test_serial_run_bots(self, bots: list[BotDriver]):
        self.test_websocket_event_contracts()

        advance_past_wait_pages(bots)

        # Both players are placed together on the WebSocket game page.
        for bot in bots:
            assert bot.current_page_label == "play_game"

        # Bots submit a full set of moves rather than playing round by round.
        # bots[0] plays rock every round, bots[1] plays scissors, so bots[0]
        # wins all five rounds.
        bots[0].take_page(response=["rock"] * N_ROUNDS)
        bots[1].take_page(response=["scissors"] * N_ROUNDS)

        advance_past_wait_pages(bots)

        assert "Final score — you: 5, partner: -5. You won the match!" in (
            bots[0].current_page_text
        )
        assert "Final score — you: -5, partner: 5. You lost the match." in (
            bots[1].current_page_text
        )

        bots[0].take_page()
        bots[1].take_page()
        advance_past_wait_pages(bots)

        assert "That's the end of the experiment!" in bots[0].current_page_text
        assert "That's the end of the experiment!" in bots[1].current_page_text
