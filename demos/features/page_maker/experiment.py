import psynet.experiment
from psynet.modular_page import NumberControl, Prompt, PushButtonControl
from psynet.page import CodeBlock, InfoPage, ModularPage
from psynet.timeline import PageMaker, Timeline, while_loop
from psynet.utils import get_logger

logger = get_logger()


class Exp(psynet.experiment.Experiment):
    label = "Page maker demo"

    timeline = Timeline(
        ModularPage(
            "choose_number",
            Prompt("What number would you like to count to?"),
            control=PushButtonControl(
                ["1", "2", "3", "4", "5"], arrange_vertically=False
            ),
            time_estimate=5,
        ),
        CodeBlock(
            lambda participant: participant.var.set("n_pages", int(participant.answer))
        ),
        PageMaker(
            lambda participant: [
                InfoPage(f"Page {i + 1}/{participant.var.n_pages}", time_estimate=1)
                for i in range(participant.var.n_pages)
            ],
            time_estimate=3,
        ),
        InfoPage(
            "We'll now test a multi-page maker that contains a code block.",
            time_estimate=5,
        ),
        PageMaker(
            lambda participant: [
                ModularPage(
                    "number_input",
                    "Give me a number to multiply by 2...",
                    NumberControl(),
                    time_estimate=5,
                    save_answer="number_to_multiply",
                ),
                CodeBlock(
                    lambda participant: participant.var.set(
                        "multiplied_number",
                        participant.var.get("number_to_multiply") * 2,
                    )
                ),
                InfoPage(
                    # Note that we have to use default values here so that we don't get an error
                    # when the function is evaluated before number_input and multiplied_number
                    # have been set.
                    f"{participant.var.get('number_to_multiply', default=0.0)} * 2 = "
                    f"{participant.var.get('multiplied_number', default=0.0)}",
                    time_estimate=5,
                ),
            ],
            time_estimate=10,
        ),
        InfoPage(
            "We'll now test a PageMaker that contains a while loop which in turn contains a PageMaker.",
            time_estimate=5,
        ),
        CodeBlock(lambda participant: participant.var.set("while_loop_counter", 0)),
        PageMaker(
            lambda participant: while_loop(
                "test",
                condition=lambda participant: participant.var.while_loop_counter < 3,
                logic=[
                    CodeBlock(
                        lambda participant: participant.var.inc("while_loop_counter")
                    ),
                    PageMaker(
                        lambda participant: InfoPage(
                            f"You are on iteration {participant.var.while_loop_counter}/3.",
                        ),
                        time_estimate=5,
                    ),
                ],
                expected_repetitions=1,
            ),
            time_estimate=5 * 3,
        ),
    )
