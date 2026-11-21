import random
from typing import Literal

from dominate import tags

import psynet.experiment
from psynet.live_game import (
    LiveGame,
    LiveGameControl,
    PlayLiveGame,
    Reject,
    TrialAnswer,
)
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.timeline import Module, PageMaker, Timeline

from .trials import ContrastTrial, trial_context, write_step

GAPS = (48, 32, 24, 16, 10, 6, 4)
START_LEVEL = 2
N_TRIALS = 8


def make_pair(level):
    """Draw the bright side once and keep the mean grey constant."""
    half_gap = GAPS[level] // 2
    left, right = random.sample([128 - half_gap, 128 + half_gap], 2)
    return {"left": left, "right": right}


class Choice(TrialAnswer):
    answer: Literal["left", "right"]


class Staircase(LiveGame):
    name = "contrast_staircase"
    min_players = max_players = 1
    messages = [Choice]
    timeout = None

    def initial_state(self, players, settings):
        return {"context": settings, "completed": 0, "level": START_LEVEL, "pair": None}

    def on_start(self, state):
        self.advance(state)

    def advance(self, state, answer=None, seconds=None):
        pair = make_pair(state["level"]) if state["completed"] < N_TRIALS else None
        state["pair"] = pair
        self.queue_effect(
            "staircase_step",
            {
                **state["context"],
                "completed": state["completed"],
                "answer": answer,
                "seconds": seconds,
                "next_pair": pair,
            },
        )

    def answer_trial(self, state, *, player, position, answer, time_taken=None):
        if position != state["completed"] or state["pair"] is None:
            raise Reject("This pair is no longer current.")
        correct = ContrastTrial.score_answer(answer, state["pair"])
        step = 1 if correct else -1
        state["level"] = max(0, min(len(GAPS) - 1, state["level"] + step))
        state["completed"] += 1
        self.advance(state, answer, time_taken)

    def view(self, state, player):
        return {"completed": state["completed"], "definition": state["pair"]}

    def is_over(self, state):
        return state["completed"] == N_TRIALS

    def outcome(self, state, reason):
        return {"completed": state["completed"]}

    def handle_effect(self, name, payload, session_row):
        if name == "staircase_step":
            write_step(session_row, payload)
        else:
            super().handle_effect(name, payload, session_row)

    def bot(self, view, player, now):
        pair = view["definition"]
        if pair:
            return Choice(
                position=view["completed"], answer=max(pair, key=pair.get), seconds=0.4
            )


def feedback(participant):
    trials = (
        ContrastTrial.query.filter_by(
            module_state_id=participant.module_state.id, complete=True
        )
        .order_by(ContrastTrial.position)
        .all()
    )
    gaps = [abs(t.definition["left"] - t.definition["right"]) for t in trials]
    return InfoPage(
        tags.div(
            tags.p(
                f"You got {sum(t.score for t in trials):.0f} of {len(trials)} correct."
            ),
            tags.p("Brightness differences, in order: " + " → ".join(map(str, gaps))),
        ),
        time_estimate=4,
    )


class Exp(psynet.experiment.Experiment):
    label = "Adaptive brightness comparison"
    timeline = Timeline(
        InfoPage(
            "Which patch is brighter? Press the left or right arrow key. Each correct answer makes the next pair more similar, until you reach the smallest difference.",
            time_estimate=5,
        ),
        Module(
            "contrast_round",
            PlayLiveGame(
                game_class=Staircase,
                settings=trial_context,
                page=ModularPage(
                    "contrast",
                    tags.div(
                        tags.p("Which patch is brighter?"),
                        tags.div(
                            *[
                                tags.span(
                                    id=f"{side}-patch",
                                    style="width:min(30vw, 180px);aspect-ratio:1",
                                )
                                for side in ("left", "right")
                            ],
                            id="patches",
                            style="display:flex;justify-content:center;gap:8%;visibility:hidden",
                        ),
                        tags.p("← Left　　Right →", cls="mt-3"),
                        cls="text-center",
                    ),
                    LiveGameControl(names="anonymous"),
                    js_page_modules=["/static/contrast.js"],
                    time_estimate=N_TRIALS * ContrastTrial.time_estimate,
                ),
            ),
            PageMaker(feedback, time_estimate=4),
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        trials = sorted(bot.all_trials, key=lambda t: t.position)
        assert [t.live_slot for t in trials] == list(range(N_TRIALS))
        assert all(
            t.complete and t.finalized and t.score == 1 and t.time_taken == 0.4
            for t in trials
        )
        assert [abs(t.definition["left"] - t.definition["right"]) for t in trials] == [
            24,
            16,
            10,
            6,
            4,
            4,
            4,
            4,
        ]
