from dominate import tags

import psynet.experiment
from psynet.page import InfoPage, JSPage
from psynet.timeline import PageMaker, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

PICTURES = [
    "red circle",
    "orange triangle",
    "yellow star",
    "green square",
    "teal hexagon",
    "blue diamond",
    "purple ring",
    "pink cross",
]
RATINGS = range(1, 6)
BREAK_AFTER = 3


class RatingTrial(StaticTrial):
    time_estimate = 2

    def show_trial(self, experiment, participant):
        name = self.definition["name"]
        return JSPage(
            "rating",
            tags.div(
                tags.p("How much do you like this picture?"),
                tags.img(
                    id="picture",
                    alt="",
                    style="width:min(60vw, 240px);aspect-ratio:1;visibility:hidden",
                ),
                tags.div(
                    *[
                        tags.button(
                            str(rating),
                            type="button",
                            cls="btn btn-outline-primary btn-lg",
                            data_rating=str(rating),
                        )
                        for rating in RATINGS
                    ],
                    cls="d-flex justify-content-center gap-2 mt-3",
                ),
                tags.p("Click a number or press 1 to 5.", cls="text-muted mt-2"),
                cls="text-center",
            ),
            contents={
                "name": name,
                "url": f"/static/pictures/{name.replace(' ', '-')}.svg",
            },
            module="/static/rate-picture.js",
            bot_response=3,
            time_estimate=self.time_estimate,
        )


class RatingTrialMaker(StaticTrialMaker):
    time_estimate_after_trials = 5

    def show_after_trial(self, trial):
        if trial.position == BREAK_AFTER:
            return InfoPage("Halfway there. Take a short break.", time_estimate=5)


def summary(participant):
    trials = RatingTrial.query.filter_by(participant_id=participant.id).order_by(
        RatingTrial.position
    )
    return InfoPage(
        "Your ratings: "
        + ", ".join(f"{trial.definition['name']} {trial.answer}" for trial in trials)
        + ".",
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Rapid ratings demo"

    timeline = Timeline(
        InfoPage(
            f"You will rate {len(PICTURES)} pictures. Each one appears as soon "
            "as you rate the one before.",
            time_estimate=5,
        ),
        RatingTrialMaker(
            id_="ratings",
            trial_class=RatingTrial,
            nodes=[StaticNode(definition={"name": name}) for name in PICTURES],
            expected_trials_per_participant=len(PICTURES),
            node_order="listed",
            prepare_trials_in_advance=True,
        ),
        PageMaker(summary, time_estimate=5),
    )

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = RatingTrial.query.filter_by(participant_id=bot.id).all()
        assert sorted(trial.definition["name"] for trial in trials) == sorted(PICTURES)
        assert all(trial.answer == 3 for trial in trials)
        assert all(trial.presented_at for trial in trials)
