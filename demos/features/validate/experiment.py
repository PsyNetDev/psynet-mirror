import pytest

import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import Response, Timeline
from psynet.utils import get_logger

logger = get_logger()


class NoGreenControl(PushButtonControl):
    def validate(self, response, **kwargs):
        if response.answer == "green":
            return "Green is an invalid answer!"


class Exp(psynet.experiment.Experiment):
    label = "Validation demo"

    timeline = Timeline(
        ModularPage(
            "colors_no_blue",
            prompt="This page has a custom validation function that prohibits the answer 'blue'.",
            control=PushButtonControl(
                ["red", "green", "blue"],
                ["Red", "Green", "Blue"],
            ),
            time_estimate=5,
            validate=lambda answer: (
                "Blue is an invalid answer!" if answer == "blue" else None
            ),
            bot_response="blue",
        ),
        ModularPage(
            "colors_no_green",
            prompt="This control has a custom validation method that prohibits the answer 'green'.",
            control=NoGreenControl(
                ["red", "green", "blue"],
                ["Red", "Green", "Blue"],
            ),
            time_estimate=5,
        ),
    )

    @classmethod
    def run_bot(cls, bot, **kwargs):
        assert bot.current_page_text.startswith(
            "This page has a custom validation function that prohibits the answer 'blue'."
        )

        with pytest.raises(
            RuntimeError, match="The participant's response was rejected"
        ):
            bot.take_page(response="blue")

        response = (
            Response.query.filter_by(participant_id=bot.id)
            .order_by(Response.creation_time.desc())
            .first()
        )
        assert response.successful_validation is not None
        assert not response.successful_validation
        assert bot.from_db("answer") is None, "A rejected answer must not be saved"
        assert bot.current_page_text.startswith(
            "This page has a custom validation function that prohibits the answer 'blue'."
        )

        bot.take_page(response="green")
        response = (
            Response.query.filter_by(participant_id=bot.id)
            .order_by(Response.creation_time.desc())
            .first()
        )
        assert response.successful_validation
        assert bot.from_db("answer") == "green"

        assert bot.current_page_text.startswith(
            "This control has a custom validation method that prohibits the answer 'green'."
        )
        with pytest.raises(
            RuntimeError, match="The participant's response was rejected"
        ):
            bot.take_page(response="green")
        response = (
            Response.query.filter_by(participant_id=bot.id)
            .order_by(Response.creation_time.desc())
            .first()
        )
        assert response.successful_validation is not None
        assert not response.successful_validation
        assert bot.current_page_text.startswith(
            "This control has a custom validation method that prohibits the answer 'green'."
        )
        bot.take_page(response="red")
        response = (
            Response.query.filter_by(participant_id=bot.id)
            .order_by(Response.creation_time.desc())
            .first()
        )
        assert response.successful_validation

        bot.run_to_completion()
