import random
from typing import Literal

from dominate import tags

import psynet.experiment
from psynet.live_game import LiveGamePage, LiveTrialGame, PlayLiveGame, TrialAnswer
from psynet.page import InfoPage
from psynet.timeline import MediaSpec, PageMaker, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

BIRDS = {
    "avocet": "left",
    "cardinal": "left",
    "jay": "right",
    "robin": "left",
    "stilt": "right",
    "waxwing": "right",
}


class BirdTrial(StaticTrial):
    time_estimate = 2

    def score_answer(self, answer, definition):
        return int(answer == definition["direction"])


class BirdAnswer(TrialAnswer):
    answer: Literal["left", "right"]


class BirdGame(LiveTrialGame):
    name = "bird_direction"
    min_players = max_players = 1
    timeout = None
    messages = [BirdAnswer]
    preload_fields = ("bird",)

    def bot(self, view, player, now):
        if view["definition"]:
            return BirdAnswer(position=view["completed"], answer="left", seconds=0.4)


class BirdTrials(StaticTrialMaker):
    def present_trials(self):
        page = LiveGamePage(
            "bird_photos",
            tags.div(
                tags.p("Which way is the beak pointing?"),
                tags.div(
                    *[
                        tags.img(
                            id=bird,
                            alt=f"Photograph of a {bird}",
                            hidden=True,
                            style="width:100%;height:100%;object-fit:contain",
                        )
                        for bird in BIRDS
                    ],
                    id="birds",
                    style="width:min(100%, 600px, 78vh);aspect-ratio:3/2;margin:auto",
                ),
                tags.p("← Left　　Right →", cls="mt-2"),
                cls="text-center",
            ),
            names="anonymous",
            media=MediaSpec(
                image={bird: f"/static/birds/{bird}.jpg" for bird in BIRDS}
            ),
            js_page_modules=["/static/birds.js"],
            time_estimate=len(BIRDS) * BirdTrial.time_estimate,
        )
        return join(
            PlayLiveGame(game_class=BirdGame, page=page),
            PageMaker(self.feedback, time_estimate=3),
        )

    def feedback(self, participant):
        trials = BirdTrial.query.filter_by(
            module_state_id=participant.module_state.id, complete=True, failed=False
        ).all()
        return InfoPage(
            f"You got {sum(t.score for t in trials):.0f} of {len(trials)} correct.",
            time_estimate=3,
        )


class Exp(psynet.experiment.Experiment):
    label = "Bird direction"
    timeline = Timeline(
        InfoPage(
            "For each photograph, press the left or right arrow key to indicate which way the bird’s beak points.",
            time_estimate=5,
        ),
        BirdTrials(
            id_="birds",
            trial_class=BirdTrial,
            nodes=[
                StaticNode(definition={"bird": bird, "direction": direction})
                for bird, direction in BIRDS.items()
            ],
            node_order=lambda nodes: random.sample(nodes, len(nodes)),
            expected_trials_per_participant=len(BIRDS),
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        trials = bot.all_trials
        assert len(trials) == len(BIRDS)
        assert {t.definition["bird"] for t in trials} == set(BIRDS)
        assert all(
            t.complete and t.finalized and t.answer == "left" and t.time_taken == 0.4
            for t in trials
        )
        assert sum(t.score for t in trials) == 3
