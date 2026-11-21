import random
from typing import Literal

from dominate import tags

import psynet.experiment
from psynet.live_game import (
    LiveGameControl,
    OnDemandTrialGame,
    PlayLiveGame,
    TrialAnswer,
)
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.timeline import PageMaker, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

GAPS = (48, 32, 24, 16, 10, 6, 4)
START_LEVEL = 2
N_TRIALS = 8


class ContrastTrial(StaticTrial):
    time_estimate = 2

    def score_answer(self, answer, definition):
        other = "right" if answer == "left" else "left"
        return int(definition[answer] > definition[other])


class Choice(TrialAnswer):
    answer: Literal["left", "right"]


class Staircase(OnDemandTrialGame):
    name = "contrast_staircase"
    answer_type = Choice

    @staticmethod
    def bot_answer(view):
        pair = view["definition"]
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


class BrightnessMaker(StaticTrialMaker):
    def select_node(self, nodes, participant, experiment):
        last = (
            ContrastTrial.query.filter_by(
                module_state_id=participant.module_state.id, complete=True
            )
            .order_by(ContrastTrial.position.desc())
            .first()
        )
        level = START_LEVEL
        if last is not None:
            gap = abs(last.definition["left"] - last.definition["right"])
            step = 1 if last.score else -1
            level = max(0, min(len(GAPS) - 1, GAPS.index(gap) + step))
        return random.choice(
            [
                node
                for node in nodes
                if abs(node.definition["left"] - node.definition["right"])
                == GAPS[level]
            ]
        )

    def present_trials(self):
        return join(
            PlayLiveGame(
                game_class=Staircase,
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
        )


class Exp(psynet.experiment.Experiment):
    label = "Adaptive brightness comparison"
    timeline = Timeline(
        InfoPage(
            "Which patch is brighter? Press the left or right arrow key. Each correct answer makes the next pair more similar, until you reach the smallest difference.",
            time_estimate=5,
        ),
        BrightnessMaker(
            id_="contrast_round",
            trial_class=ContrastTrial,
            nodes=[
                StaticNode(definition={"left": 128 + delta, "right": 128 - delta})
                for gap in GAPS
                for delta in (gap // 2, -gap // 2)
            ],
            allow_repeated_nodes=True,
            max_trials_per_participant=N_TRIALS,
            expected_trials_per_participant=N_TRIALS,
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        trials = sorted(bot.all_trials, key=lambda t: t.position)
        assert [t.position for t in trials] == list(range(N_TRIALS))
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
