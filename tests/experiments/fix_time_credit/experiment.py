import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import CodeBlock, Timeline, while_loop

# This experiment is written to test that the 'time credit bound' functionality
# works appropriately.


def assert_no_time_credit_fixes(participant):
    assert len(participant.time_credit_fixes) == 0, (
        f"Expected no time credit bounds, got {participant.time_credit_fixes}"
    )


def assert_time_credit(participant, value):
    assert participant.time_credit == value, (
        f"Expected time credit to be {value}, got {participant.time_credit}"
    )


class Exp(psynet.experiment.Experiment):
    label = "Testing time credit bounds"

    timeline = Timeline(
        CodeBlock(lambda participant: participant.var.set("counter", 0)),
        while_loop(
            "test_while_loop_0",
            condition=lambda participant: participant.var.counter < 5,  # noqa
            logic=[
                InfoPage("Please click 'Next'", time_estimate=1.0),
                CodeBlock(lambda participant: participant.var.inc("counter")),
            ],
            # This is an underestimate! But the fix_time_credit functionality should
            # cap the resulting credit.
            expected_repetitions=1,
            fix_time_credit=True,
        ),
        CodeBlock(assert_no_time_credit_fixes),
        CodeBlock(lambda participant: assert_time_credit(participant, 1.0)),
        CodeBlock(lambda participant: participant.var.set("counter", 0)),
        while_loop(
            "test_while_loop_1",
            condition=lambda participant: participant.var.counter < 5,  # noqa
            logic=[
                CodeBlock(assert_no_time_credit_fixes),
                InfoPage("Please click 'Next'", time_estimate=1.0),
                CodeBlock(lambda participant: participant.var.inc("counter")),
            ],
            # Since fix_time_credit is set to False, the time credit should now
            # no longer be limited by expected_repetitions.
            expected_repetitions=1,
            fix_time_credit=False,
        ),
        CodeBlock(assert_no_time_credit_fixes),
        CodeBlock(lambda participant: assert_time_credit(participant, 1.0 + 5.0)),
    )
