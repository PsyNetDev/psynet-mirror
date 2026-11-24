"""
An Eriksen flanker task: participants report which way the middle arrow points
while the arrows around it point the same way or the other way.
"""

import random
from statistics import mean

from dominate import tags

import psynet.experiment
from psynet.bot import BotResponse
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.timeline import FailedValidation, PageMaker, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

TRIALS_PER_CONDITION = 8
TIMINGS = {"blank_ms": 400, "fixation_ms": 500, "deadline_ms": 1500}
ANSWERS = ("left", "right", "timeout")
ARROWS = {"left": "←", "right": "→"}


def get_nodes():
    """One node per trial: each target direction, congruent and incongruent."""
    return [
        StaticNode(definition={"target": target, "congruent": congruent})
        for target in ("left", "right")
        for congruent in (True, False)
        for _ in range(TRIALS_PER_CONDITION // 2)
    ]


N_TRIALS = len(get_nodes())


def arrows(target, congruent):
    flanker = target if congruent else ("right" if target == "left" else "left")
    return ARROWS[flanker] * 2 + ARROWS[target] + ARROWS[flanker] * 2


class FlankerTrial(StaticTrial):
    time_estimate = 2

    def show_trial(self, experiment, participant):
        return ModularPage(
            "flanker",
            tags.div(
                tags.div(id="flanker-stimulus", cls="flanker-stimulus"),
                tags.div(
                    *[
                        tags.button(
                            f"{ARROWS[side]} {key}",
                            type="button",
                            cls="btn btn-outline-secondary btn-lg",
                            data_response=side,
                            aria_label=side,
                        )
                        for side, key in (("left", "F"), ("right", "J"))
                    ],
                    cls="d-flex justify-content-center gap-5 mt-4",
                ),
                cls="text-center",
            ),
            contents={
                "arrows": arrows(
                    self.definition["target"], self.definition["congruent"]
                )
            },
            page_config={"flanker": {"timings": TIMINGS}},
            js_page_modules=["/static/flanker.js"],
            css=[
                ".flanker-stimulus { height: 6rem; display: flex; "
                "align-items: center; justify-content: center; "
                "font: 3.5rem monospace; letter-spacing: 0.2em; }"
            ],
            show_next_button=False,
            validate=validate_answer,
            bot_response=bot_response,
            time_estimate=self.time_estimate,
        )

    def score_answer(self, answer, definition):
        return int(answer == definition["target"])


class FlankerTrialMaker(StaticTrialMaker):
    def show_after_trial(self, trial):
        if trial.position == N_TRIALS // 2 - 1:
            return InfoPage(
                "Halfway there. Take a short break, then press Next to continue.",
                time_estimate=10,
            )


def validate_answer(answer):
    if answer not in ANSWERS:
        return FailedValidation(f"Unexpected answer {answer!r}.")
    return None


def bot_response(page, bot):
    """Answer correctly 95% of the time, about 60 ms slower when incongruent."""
    stimulus = page.contents["arrows"]
    target = "left" if stimulus[2] == ARROWS["left"] else "right"
    incongruent = stimulus[0] != stimulus[2]
    other = "right" if target == "left" else "left"
    answer = target if random.random() < 0.95 else other
    rt = random.gauss(0.45 + 0.06 * incongruent, 0.06)
    return BotResponse(answer=answer, metadata={"time_taken": max(rt, 0.2)})


def participant_trials(participant):
    return (
        FlankerTrial.query.filter_by(
            participant_id=participant.id, complete=True, failed=False
        )
        .order_by(FlankerTrial.position)
        .all()
    )


def mean_rt_ms(trials, congruent):
    rts = [
        t.time_taken * 1000
        for t in trials
        if t.score and t.definition["congruent"] == congruent
    ]
    return mean(rts) if rts else None


def summary(participant):
    trials = participant_trials(participant)
    congruent = mean_rt_ms(trials, True)
    incongruent = mean_rt_ms(trials, False)
    accuracy = mean(t.score for t in trials) if trials else 0
    lines = [f"You answered {accuracy:.0%} of the trials correctly."]
    if congruent is not None and incongruent is not None:
        lines += [
            f"Mean reaction time when all arrows agreed: {congruent:.0f} ms.",
            f"Mean reaction time when they disagreed: {incongruent:.0f} ms.",
        ]
    return InfoPage(
        tags.div(*[tags.p(line) for line in lines], id="summary"), time_estimate=5
    )


class Exp(psynet.experiment.Experiment):
    label = "Flanker task"

    timeline = Timeline(
        InfoPage(
            tags.div(
                tags.p(
                    "In each trial, a row of five arrows appears after a cross. "
                    "Report which way the middle arrow points: press F for left "
                    "and J for right, or tap the buttons below the arrows."
                ),
                tags.p("Answer as quickly and accurately as you can."),
            ),
            time_estimate=10,
        ),
        FlankerTrialMaker(
            id_="flanker",
            trial_class=FlankerTrial,
            nodes=get_nodes,
            expected_trials_per_participant=N_TRIALS,
            node_order="random",
            prepare_trials_in_advance=True,
        ),
        PageMaker(summary, time_estimate=5),
    )

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        return {
            "trials": [
                {
                    "participant_id": t.participant_id,
                    "position": t.position,
                    "target": t.definition["target"],
                    "congruent": t.definition["congruent"],
                    "answer": t.answer,
                    "correct": bool(t.score),
                    "rt_ms": t.time_taken * 1000,
                }
                for t in FlankerTrial.query.filter_by(
                    complete=True, failed=False
                ).order_by(FlankerTrial.participant_id, FlankerTrial.position)
            ]
        }

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = participant_trials(bot)
        assert len(trials) == N_TRIALS
        assert sum(t.definition["congruent"] for t in trials) == N_TRIALS // 2
        assert all(t.answer in ANSWERS for t in trials)
        # The break doesn't count towards the trials around it.
        assert all(0.2 <= t.time_taken < 1 for t in trials)
