import random
from collections import Counter
from typing import Literal

from dominate import tags
from pydantic import Field

import psynet.experiment
from psynet.live_game import LiveGameControl, LiveMessage, LiveTrialGame, PlayLiveGame
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.timeline import PageMaker, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

PATTERNS = ["←←←←←", "→→→→→", "→→←→→", "←←→←←"]
N_TRIALS = 2 * len(PATTERNS)


class ArrowTrial(StaticTrial):
    time_estimate = 2

    def score_answer(self, answer, definition):
        return int(answer == definition["arrows"][2])


class ArrowKey(LiveMessage):
    type = "arrow_key"
    position: int = Field(ge=0, strict=True)
    direction: Literal["←", "→"]
    seconds: float = Field(ge=0, allow_inf_nan=False)

    def apply(self, game, state, player, now):
        game.answer_trial(
            state,
            player=player,
            position=self.position,
            answer=self.direction,
            time_taken=self.seconds,
        )


class FlankerGame(LiveTrialGame):
    name = "flanker"
    min_players = max_players = 1
    timeout = None
    messages = [ArrowKey]
    preload_fields = ("arrows",)

    def bot(self, view, player, now):
        if view["definition"] is not None:
            return ArrowKey(
                position=view["completed"],
                direction=view["definition"]["arrows"][2],
                seconds=0.4,
            )


class FlankerTrials(StaticTrialMaker):
    def present_trials(self):
        page = ModularPage(
            "arrows",
            tags.div(
                id="arrows",
                role="status",
                cls="text-center",
                style="font: clamp(2rem, 9vw, 5rem) monospace; min-height: 1.4em",
            ),
            LiveGameControl(names="anonymous"),
            js_page_modules=["/static/flanker.js"],
            time_estimate=N_TRIALS * ArrowTrial.time_estimate,
        )
        return join(
            PlayLiveGame(game_class=FlankerGame, page=page),
            PageMaker(self.feedback, time_estimate=3),
        )

    def feedback(self, participant):
        trials = ArrowTrial.query.filter_by(
            module_state_id=participant.module_state.id, complete=True, failed=False
        ).all()
        correct = sum(trial.score for trial in trials)
        return InfoPage(
            f"You got {correct:.0f} of {len(trials)} correct.", time_estimate=3
        )


class Exp(psynet.experiment.Experiment):
    label = "Arrow flanker"
    timeline = Timeline(
        InfoPage(
            "Press the left or right arrow key to match the middle arrow.",
            time_estimate=4,
        ),
        FlankerTrials(
            id_="arrows",
            trial_class=ArrowTrial,
            nodes=[StaticNode(definition={"arrows": arrows}) for arrows in PATTERNS],
            node_order=lambda nodes: random.sample(nodes * 2, k=N_TRIALS),
            allow_repeated_nodes=True,
            expected_trials_per_participant=N_TRIALS,
            max_trials_per_participant=N_TRIALS,
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        trials = sorted(bot.all_trials, key=lambda trial: trial.position)
        assert [trial.position for trial in trials] == list(range(N_TRIALS))
        assert Counter(trial.definition["arrows"] for trial in trials) == dict.fromkeys(
            PATTERNS, 2
        )
        assert all(
            trial.complete and trial.finalized and trial.score == 1 for trial in trials
        )
        assert all(trial.time_taken == 0.4 for trial in trials)
