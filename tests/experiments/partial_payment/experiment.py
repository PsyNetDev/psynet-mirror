"""
This experiment tests different routes of participant payment in PsyNet,
specifically focusing on:
1. Full payment with bonus (approved participants)
2. Partial payment for failed participants who contact the experimenter
3. Partial payment for returned assignments

Payment Routes:
---------------
1. Approved Participants (ID=1):
   - Base payment: £1.00
   - Bonus: £3.50
   - Total: £4.50
   - Route: Completes full experiment

2. Manual partial payment Participants (ID=2):
   - Partial payment: ~£0.17-0.18 (based on time spent)
   - No bonus
   - Route: Fails at prescreener stage

3. Returned Assignment (ID=3):
   - Partial payment: ~£0.17-0.18 (based on time spent)
   - No bonus
   - Route: Assignment is returned after completion

The experiment uses participant.var to track the route taken through the timeline,
which is then verified in the test_check_bot method.
"""

# pylint: disable=unused-import,abstract-method,unused-argument

import psynet.experiment
from psynet.bot import Bot
from psynet.consent import NoConsent
from psynet.page import InfoPage, UnsuccessfulEndPage
from psynet.timeline import CodeBlock, Timeline, conditional
from psynet.utils import get_logger

logger = get_logger()

BONUS = 3.5


class Exp(psynet.experiment.Experiment):
    label = "Trying to make a partial payment"
    config = {
        "prolific_workspace": "test_workspace",
        "prolific_project": "test_project",
        "prolific_enable_return_for_bonus": False,
        # This experiment tests the manual/returned partial-payment routes,
        # so disable the (default-on) automatic screen-out payment, which
        # would otherwise require `prolific_screen_out_slots` and reroute
        # failed participants through the UNSUCCESSFUL completion code.
        "prolific_pay_unsuccessful": False,
    }

    test_n_bots = 3

    base_payment = 1.0
    recruiter_ = "prolific"
    wage_per_hour = 10.0

    def __init__(self, *args, **kwargs):
        """Override config values after initialization"""
        super().__init__(*args, **kwargs)
        # Force the values from experiment.py to take precedence over config.txt
        from dallinger.config import get_config

        config = get_config()
        config.set("base_payment", self.base_payment)
        config.set("recruiter", self.recruiter_)
        config.set("wage_per_hour", self.wage_per_hour)

    timeline = Timeline(
        NoConsent(),
        InfoPage("Let's imagine this is the prescreener", time_estimate=60),
        CodeBlock(
            lambda participant: participant.var.set("route", "prescreener_completed")
        ),
        conditional(
            "decide_whether_to_fail_participant",
            lambda participant: participant.id == 2,
            logic_if_true=[
                CodeBlock(
                    lambda participant: participant.var.set(
                        "route", "manual_partial_payment"
                    )
                ),
                UnsuccessfulEndPage(),
            ],
        ),
        conditional(
            "decide_whether_to_fail_participant",
            lambda participant: participant.id == 3,
            logic_if_true=[
                CodeBlock(
                    lambda participant: participant.var.set(
                        "route", "returned_partial_payment"
                    )
                ),
                UnsuccessfulEndPage(),
            ],
        ),
        InfoPage("Let's imagine this is the main experiment", time_estimate=60 * 5),
        CodeBlock(
            lambda participant: participant.var.set(
                "route", "main_experiment_completed"
            )
        ),
        CodeBlock(lambda participant: participant.inc_performance_reward(BONUS)),
        CodeBlock(lambda participant: participant.var.set("route", "bonus_awarded")),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        route = bot.var.get("route")

        if bot.id == 1:
            assert route == "bonus_awarded", (
                f"Expected route 'bonus_awarded', got '{route}'"
            )
            assert bot.status == "approved", (
                f"Expected status for bot ID {bot.id} to be 'approved', but got '{bot.status}'"
            )
            # Ensure the status is committed and refresh the bot object to get the latest status
            from psynet.experiment import db

            db.session.commit()
            db.session.refresh(bot)

            assert self.base_payment == 1.0

            decision = bot.recruiter.decide_payment(bot, experiment=self)
            assert decision.bonus == BONUS, (
                f"Expected bonus for bot ID {bot.id} to be 3.5, but got {decision.bonus} (status: {bot.status}, time_reward: {bot.time_reward}, performance_reward: {bot.performance_reward}, bot.bonus: {bot.bonus})"
            )
        elif bot.id == 2:
            assert route == "manual_partial_payment", (
                f"Expected route 'manual_partial_payment', got '{route}'"
            )
            assert bot.failed, f"Expected bot ID {bot.id} to be marked as failed."
            assert bot.calculate_reward() in (
                0.17,
                0.18,
            ), (
                f"Expected accumulated reward for bot ID {bot.id} to be either "
                f"0.17 or 0.18, but got {bot.calculate_reward()}"
            )
        elif bot.id == 3:
            assert route == "returned_partial_payment", (
                f"Expected route 'returned_partial_payment', got '{route}'"
            )
            # Simulate the participant returning their assignment
            self.assignment_returned(bot)
            # Explicitly set the status to "returned" for testing
            # In a real Prolific environment, this would be set by run_recruiter_checks scheduled_task
            bot.status = "returned"
            bot.failed = True
            assert bot.status == "returned", (
                f"Expected status for bot ID {bot.id} to be 'returned', but got '{bot.status}'"
            )
            decision = bot.recruiter.decide_payment(bot, experiment=self)
            assert decision.bonus in (
                0.17,
                0.18,
            ), (
                f"Expected bonus for bot ID {bot.id} to be either 0.17 or 0.18, but got {decision.bonus}"
            )
        else:
            raise ValueError(f"Unexpected bot id: {bot.id}")
