import pytest

import psynet.experiment
from psynet.page import InfoPage, WaitPage
from psynet.timeline import CodeBlock, Timeline, while_loop

# This experiment is written to test that the 'progress bound' functionality
# works appropriately; in particular, we check that if the participant
# takes more iterations of the while loop than expected, the resulting
# progress value still does not exceed what is expected.


def assert_progress_is_less_than_one(participant):
    assert participant.progress < 1.0


def assert_progress(participant, value):
    assert participant.progress == pytest.approx(value), (
        f"Expected progress to be {value}, got {participant.progress}"
    )


class Exp(psynet.experiment.Experiment):
    label = "Testing progress bounds"

    timeline = Timeline(
        CodeBlock(lambda participant: participant.var.set("counter", 0)),
        while_loop(
            "test_while_loop_1",
            condition=lambda participant: participant.var.counter < 5,  # noqa
            logic=[
                InfoPage("Please click 'Next'", time_estimate=1.0),
                CodeBlock(lambda participant: participant.var.inc("counter")),
            ],
            # Here the expected_repetitions parameter has been underestimated.
            # We will check that this doesn't cause the progress functionality to break.
            expected_repetitions=1,
        ),
        CodeBlock(
            lambda participant: assert_progress(
                participant, 1.0 / participant.estimated_max_time_credit
            )
        ),
        WaitPage(wait_time=1.0),
        CodeBlock(lambda participant: participant.var.set("counter", 0)),
        while_loop(
            "test_while_loop_1",
            condition=lambda participant: participant.var.counter < 1,  # noqa
            logic=[
                InfoPage("Please click 'Next'", time_estimate=1.0),
                CodeBlock(lambda participant: participant.var.inc("counter")),
            ],
            # Here the expected_repetitions parameter has been *overestimated*.
            expected_repetitions=3,
        ),
        CodeBlock(
            lambda participant: assert_progress(
                participant, (1 + 1 + 3) / participant.estimated_max_time_credit
            )
        ),
        WaitPage(wait_time=1.0),
    )
