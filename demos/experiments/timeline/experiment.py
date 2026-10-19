import math
from datetime import datetime

import numpy
from dallinger import db
from dallinger.experiment import experiment_route
from dallinger.experiment_server.utils import error_response, success_response
from dominate import tags
from flask import request

import psynet.experiment
from psynet.consent import MainConsent
from psynet.modular_page import (
    ModularPage,
    NumberControl,
    Prompt,
    PushButtonControl,
    TextControl,
    TimedPushButtonControl,
)
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.timeline import (
    CodeBlock,
    Module,
    PageMaker,
    Timeline,
    conditional,
    switch,
    while_loop,
)


class Exp(psynet.experiment.Experiment):
    label = "Timeline demo"

    variables = {
        "new_variable": "some-value",
        "max_participant_payment": 10.0,
    }

    config = {
        "min_reward_for_paid_early_exit": 0.15,
        "show_early_exit_button": True,
    }

    @experiment_route("/custom_route", methods=["POST", "GET"])
    @classmethod
    def custom_route(cls):
        return f"A custom route for {cls.__name__}."

    @experiment_route("/set_dollars", methods=["POST"])
    @classmethod
    def set_dollars(cls):
        try:
            participant_id = int(request.values["participant_id"])
            dollars = float(request.values["dollars"])
        except (KeyError, ValueError):
            return error_response(error_text="Invalid request")
        participant = Participant.query.filter_by(id=participant_id).one_or_none()
        if (
            participant is None
            or participant.unique_id != request.values.get("unique_id")
            or not math.isfinite(dollars)
        ):
            return error_response(error_text="Invalid request")
        participant.var.dollars = dollars
        db.session.commit()
        return success_response()

    timeline = Timeline(
        MainConsent(),
        InfoPage(
            tags.div(
                tags.h2("Welcome"),
                tags.p("Welcome to the experiment!"),
            ),
            time_estimate=5,
        ),
        Module(
            "introduction",
            # You can set arbitrary variables with the participant object
            # inside code blocks. Here we set a variable called 'numpy_test',
            # and the value is an object from the numpy package (numpy.nan).
            CodeBlock(lambda participant: participant.var.set("numpy_test", numpy.nan)),
            PageMaker(
                lambda: InfoPage(
                    f"The current time is {datetime.now().strftime('%H:%M:%S')}."
                ),
                time_estimate=5,
            ),
            ModularPage(
                "message",
                tags.p(
                    "Write me a ",
                    tags.span("message", style="color: red"),
                    "!",
                ),
                control=TextControl(one_line=False),
                time_estimate=5,
                save_answer=True,
            ),
            PageMaker(
                lambda participant: InfoPage(f"Your message: {participant.answer}"),
                time_estimate=5,
            ),
        ),
        Module(
            "weight",
            ModularPage(
                "weight",
                Prompt("What is your weight in kg?"),
                NumberControl(),
                time_estimate=5,
                save_answer="weight",
            ),
            PageMaker(
                lambda participant: InfoPage(
                    f"Your weight is {participant.var.weight} kg."
                ),
                time_estimate=5,
            ),
        ),
        ModularPage(
            "timed_push_button",
            Prompt(
                """
                This is a TimedPushButtonControl. You can press the buttons 'A', 'B', 'C'
                in any order, as many times as you like, and the timings will be logged.
                Press 'Next' when you're ready to continue.
                """
            ),
            TimedPushButtonControl(choices=["A", "B", "C"], arrange_vertically=False),
            time_estimate=5,
        ),
        Module(
            "chocolate",
            ModularPage(
                "chocolate",
                Prompt("Do you like chocolate?"),
                control=PushButtonControl(["Yes", "No"]),
                time_estimate=3,
            ),
            conditional(
                "like_chocolate",
                lambda participant: participant.answer == "Yes",
                InfoPage("It's nice to hear that you like chocolate!", time_estimate=6),
                InfoPage(
                    "I'm sorry to hear that you don't like chocolate...",
                    time_estimate=3,
                ),
                fix_time_credit=False,
            ),
        ),
        CodeBlock(lambda participant: participant.set_answer("Yes")),
        while_loop(
            "example_loop",
            lambda participant: participant.answer == "Yes",
            Module(
                "loop",
                ModularPage(
                    "loop_nafc",
                    Prompt("Would you like to stay in this loop?"),
                    control=PushButtonControl(["Yes", "No"], arrange_vertically=False),
                    time_estimate=3,
                ),
            ),
            expected_repetitions=3,
            fix_time_credit=True,
        ),
        Module(
            "PageMaker with multiple pages",
            InfoPage(
                """
                It is possible to generate multiple pages from the same
                PageMaker, as in the following example:
                """,
                time_estimate=5,
            ),
            PageMaker(
                lambda participant: [
                    ModularPage(
                        "shape",
                        Prompt(f"Participant {participant.id}, choose a shape:"),
                        control=PushButtonControl(
                            ["Square", "Circle"], arrange_vertically=False
                        ),
                        time_estimate=5,
                    ),
                    ModularPage(
                        "chord",
                        Prompt(f"Participant {participant.id}, choose a chord:"),
                        control=PushButtonControl(
                            ["Major", "Minor"], arrange_vertically=False
                        ),
                        time_estimate=5,
                    ),
                ],
                time_estimate=10,
                accumulate_answers=True,
            ),
            PageMaker(
                lambda participant: InfoPage(
                    (
                        "If accumulate_answers is True, then the answers are stored in a dictionary, in this case: "
                        + f"{participant.answer}."
                    ),
                    time_estimate=5,
                ),
                time_estimate=5,
            ),
        ),
        Module(
            "color",
            ModularPage(
                "test_nafc",
                Prompt("What's your favourite color?"),
                control=PushButtonControl(
                    ["Red", "Green", "Blue"], arrange_vertically=False
                ),
                time_estimate=5,
            ),
            CodeBlock(
                lambda participant: participant.var.new(
                    "favourite_color", participant.answer
                )
            ),
            switch(
                "color",
                lambda participant: participant.answer,
                branches={
                    "Red": InfoPage("Red is a nice color, wait 1s.", time_estimate=1),
                    "Green": InfoPage(
                        "Green is quite a nice color, wait 2s.", time_estimate=2
                    ),
                    "Blue": InfoPage(
                        "Blue is an unpleasant color, wait 3s.", time_estimate=3
                    ),
                },
                fix_time_credit=False,
            ),
        ),
    )
