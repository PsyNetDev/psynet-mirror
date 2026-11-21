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
from psynet.trial.staircase import (
    GeometricStaircaseNode,
    GeometricStaircaseTrial,
    GeometricStaircaseTrialMaker,
)

GAPS = (48, 32, 24, 16, 10, 6, 4)
START_GAP = 24
N_TRIALS = 8


class ContrastNode(GeometricStaircaseNode):
    k = 1

    def increase_difficulty(self, parameter):
        return GAPS[min(GAPS.index(parameter) + 1, len(GAPS) - 1)]

    def decrease_difficulty(self, parameter):
        return GAPS[max(GAPS.index(parameter) - 1, 0)]


class ContrastTrial(GeometricStaircaseTrial):
    time_estimate = 2

    def finalize_definition(self, definition, experiment, participant):
        # Draw the brighter side once, so a reload shows the assigned pair.
        delta = random.choice((-1, 1)) * (definition["parameter"] // 2)
        return {**definition, "left": 128 + delta, "right": 128 - delta}

    def score_answer(self, answer, definition):
        other = "right" if answer == "left" else "left"
        return int(definition[answer] > definition[other])


class Choice(TrialAnswer):
    answer: Literal["left", "right"]


class BrightnessGame(OnDemandTrialGame):
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
    gaps = [t.parameter for t in trials]
    return InfoPage(
        tags.div(
            tags.p(
                f"You got {sum(t.score for t in trials):.0f} of {len(trials)} correct."
            ),
            tags.p("Brightness differences, in order: " + " → ".join(map(str, gaps))),
        ),
        time_estimate=4,
    )


class BrightnessMaker(GeometricStaircaseTrialMaker):
    def live_trial_definition(self, trial):
        return {side: trial.definition[side] for side in ("left", "right")}

    def present_trials(self):
        return join(
            PlayLiveGame(
                game_class=BrightnessGame,
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
            node_class=ContrastNode,
            start_nodes=lambda participant: [ContrastNode(parameter=START_GAP)],
            max_nodes_per_chain=N_TRIALS,
            # Everyone completes the round, including players with no reversals.
            check_performance_at_end=False,
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
        assert len({t.network_id for t in trials}) == 1
        assert all(
            t.node.degree == t.position
            and t.node.parameter == t.parameter
            and abs(t.definition["left"] - t.definition["right"]) == t.parameter
            for t in trials
        )
        assert [t.parameter for t in trials] == [
            24,
            16,
            10,
            6,
            4,
            4,
            4,
            4,
        ]
