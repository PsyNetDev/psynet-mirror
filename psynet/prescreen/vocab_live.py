"""Present a prepared vocabulary form in one live session and score it at the boundary."""

import random
from typing import Literal

from dominate import tags
from pydantic import Field

from psynet.live_game import LiveGameControl, LiveMessage, LiveTrialGame, PlayLiveGame
from psynet.modular_page import ModularPage
from psynet.page import InfoPage, UnsuccessfulEndPage
from psynet.sync import SimpleGrouper, leave_group
from psynet.timeline import PageMaker, conditional, join
from psynet.utils import get_translator

_ = get_translator()


class WordResponse(LiveMessage):
    type = "classify"
    position: int = Field(ge=0, strict=True)
    choice: Literal["real", "fake"]
    seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    def apply(self, game, state, player, now):
        game.answer_trial(
            state,
            player=player,
            position=self.position,
            answer=self.choice,
            time_taken=self.seconds,
        )


class VocabularyGame(LiveTrialGame):
    name = "psynet_vocabulary"
    messages = [WordResponse]
    min_players = max_players = 1
    preload_fields = ("stimulus", "image")

    def bot(self, view, player, now):
        if view["definition"] is not None:
            return WordResponse(
                position=view["completed"], choice=random.choice(["real", "fake"])
            )


def _form(maker, number, group_type):
    game_id = f"{maker.id}_form_{number}"

    def finished(participant):
        return participant.live_games[game_id].finished

    def feedback(participant):
        score = maker.score_form(participant, maker.get_participant_trials(participant))
        return InfoPage(
            _("Your score was")
            + f" {score:.0%}. "
            + _("Press the button to continue."),
            time_estimate=5,
        )

    def choice(value, label, key):
        caption = f"{label} ({key})" if maker.use_keyboard else label
        if maker.use_buttons:
            return tags.button(
                caption,
                type="button",
                disabled=True,
                data_choice=value,
                cls="btn btn-outline-secondary mx-1",
            )
        return tags.span(caption, cls="mx-2")

    height = maker.image_height if maker.present_as_image else 260
    page = ModularPage(
        "vocabtest",
        tags.div(
            tags.div(
                id="test-stimulus",
                role="status",
                style=(
                    f"min-height:min({height}px,55vh);display:grid;place-items:center;"
                    "font-size:clamp(2rem,7vw,5rem);font-weight:bold"
                ),
            ),
            choice("real", _("Real"), maker.true_key_label),
            choice("fake", _("Fake"), maker.false_key_label),
            cls="text-center",
        ),
        LiveGameControl(names="anonymous"),
        js_vars={
            "vocab": {
                "trueKey": maker.true_key_button,
                "falseKey": maker.false_key_button,
                "keyboard": maker.use_keyboard,
                "buttons": maker.use_buttons,
                "hideAfter": maker.hide_after,
                "lag": maker.lag_between_items,
                "width": getattr(maker, "image_width", None),
            }
        },
        js_page_modules=["/static/scripts/vocabtest.js"],
        time_estimate=maker.form_size * maker.trial_class.time_estimate,
    )
    return join(
        PlayLiveGame(
            id_=game_id,
            group_type=group_type,
            game_class=VocabularyGame,
            settings={"stop": number * maker.form_size},
            page=page,
            max_wait_time=60,
            max_wait_action="leave_group",
        ),
        conditional(
            f"{game_id}_finished",
            finished,
            join(
                PageMaker(feedback, time_estimate=5) if maker.show_feedback else None,
                maker._check_performance_logic(type="trial"),
            ),
            UnsuccessfulEndPage(failure_tags=["incomplete_vocabulary_form"]),
        ),
    )


def present_forms(maker):
    group_type = f"{maker.id}_solo"
    return join(
        SimpleGrouper(group_type=group_type, initial_group_size=1, max_wait_time=60),
        *[_form(maker, number, group_type) for number in range(1, maker.n_trials + 1)],
        leave_group(group_type),
    )
