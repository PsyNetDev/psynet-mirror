import random
from typing import Optional

import psynet.experiment
from psynet.consent import MainConsent
from psynet.page import InfoPage, UnityPage
from psynet.participant import Participant
from psynet.timeline import Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import get_logger

logger = get_logger("experiment")

DEBUG = False
GAINS = ["2", "3", "4"]  # Points for collecting an object; one condition per value
GOAL = 3  # Once the score reaches this goal the game is finished

SAME_SESSION_ID = "0"

# One node per between-participant condition. Each participant is assigned to
# one gain at random (see choose_participant_group below) and plays that
# condition's node for several rounds.
nodes = [
    StaticNode(
        definition={"gain": gain},
        participant_group=gain,
    )
    for gain in GAINS
]


class UnityGamePage(UnityPage):
    def __init__(
        self,
        contents: dict,
        session_id: str,
        time_estimate: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(
            title="Unity Game",
            resources="/static",
            contents=contents,
            session_id=session_id,
            debug=DEBUG,
            time_estimate=time_estimate,
            game_container_width="960px",
            game_container_height="600px",
            **kwargs,
        )

    def format_answer(self, raw_answer, **kwargs):
        logger.info("----------------- format answer -----------------")
        logger.info(raw_answer)
        return raw_answer


class GameTrial(StaticTrial):
    accumulate_answers = False  # We create pages one by one, saves only one page
    time_estimate = 1

    def show_trial(self, experiment, participant):
        gain = self.definition["gain"]
        goal = GOAL
        data = {
            "goal": goal,
            "gain": gain,
        }

        page = UnityGamePage(
            # Send this string to Unity
            contents=data,
            # We stay in the same session.
            session_id=SAME_SESSION_ID,
            time_estimate=1,
            bot_response={"reward": 50, "expire": True},
        )
        return page  # list_of_pages


class GameTrialMaker(StaticTrialMaker):
    response_timeout_sec = 1000

    def prepare_trial(self, experiment, participant):
        if participant.var.has("expire"):  # Finish the game
            logger.info("Ending game")
            return None, "exit"
        return super().prepare_trial(experiment, participant)

    def finalize_trial(self, answer, trial, experiment, participant: Participant):
        # Pay reward
        participant.inc_performance_reward(answer["reward"] / 100)

        # Check time to finish experiment
        if answer["expire"]:
            participant.var.expire = True  # Finish the game
            super().finalize_trial(answer, trial, experiment, participant)
            return
        super().finalize_trial(answer, trial, experiment, participant)

    def compute_performance_reward(self, score, passed):
        logger.info(f"SCORE in compute_performance_reward: {score}")
        return score / 100

    def performance_check(self, experiment, participant, participant_trials):
        if participant.var.has("expire"):
            if participant.var.expire:
                return {"score": 0, "passed": True}
        score = 0
        for trial in participant_trials:
            score = 0  # score + number_of_coins_in_trial
        logger.info(f"SCORE: {score}")
        passed = True
        return {"score": score, "passed": passed}


trial_maker = GameTrialMaker(
    id_="game",
    trial_class=GameTrial,
    nodes=nodes,
    max_trials_per_participant=3,
    expected_trials_per_participant=3,
    allow_repeated_nodes=True,
    balance_across_nodes=True,
    check_performance_at_end=True,
    check_performance_every_trial=False,
    target_n_participants=3,
    recruit_mode="n_participants",
    n_repeat_trials=0,
    choose_participant_group=lambda participant: random.choice(GAINS),
)


# Experiment
class Exp(psynet.experiment.Experiment):
    label = "Unity autoplay demo"

    timeline = Timeline(
        MainConsent(),
        trial_maker,  # The Unity game
        InfoPage("You finished the experiment!", time_estimate=0),
    )
