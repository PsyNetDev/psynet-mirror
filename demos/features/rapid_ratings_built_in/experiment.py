import psynet.experiment
from psynet.modular_page import ImagePrompt, ModularPage, PushButtonControl
from psynet.page import InfoPage
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
BREAK_AFTER = 3


class RatingTrial(StaticTrial):
    time_estimate = 2

    def show_trial(self, experiment, participant):
        name = self.definition["name"]
        return ModularPage(
            "rating",
            ImagePrompt(
                f"/static/pictures/{name.replace(' ', '-')}.svg",
                "How much do you like this picture?",
                width="240px",
                height="240px",
            ),
            PushButtonControl(
                ["1", "2", "3", "4", "5"],
                arrange_vertically=False,
                bot_response="3",
            ),
            time_estimate=self.time_estimate,
        )


class RatingTrialMaker(StaticTrialMaker):
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
    label = "Rapid ratings with built-in pages demo"

    timeline = Timeline(
        InfoPage(
            f"You will rate {len(PICTURES)} pictures. Each one appears as soon "
            "as you rate the one before.",
            time_estimate=5,
        ),
        # Rendered in advance, so it appears as soon as the participant clicks Next.
        InfoPage(
            "Rate each picture from 1 (not at all) to 5 (very much).",
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
        trials = RatingTrial.query.filter_by(participant_id=bot.id).all()
        assert sorted(trial.definition["name"] for trial in trials) == sorted(PICTURES)
        assert all(trial.answer == "3" for trial in trials)
