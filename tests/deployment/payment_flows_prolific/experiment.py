"""
Prolific Recruiter Test Experiment
==================================

This experiment is designed to test the integration between PsyNet and the Prolific recruiter.
It simulates different participant flows to ensure that screen-out and reward mechanisms work as expected
when using Prolific.

Participants are assigned to one of four experiment flows based on their participant ID (ID % 4):
    0. **Normal plus performance reward**: Participant completes the full experiment and also receives
        a performance reward increment. They get base payment plus £0.10 bonus.
    1. **Normal**: Participant completes a simple flow (consent, info pages, and debrief; ~4.5 minutes
        estimated). They get the full £0.50 base payment.
    2. **Failed prescreening**: Participant fails a prescreen after accruing 3 minutes (1-minute consent
        plus 2-minute info page), i.e. £0.50 at wage_per_hour = 10.
    3. **Errored**: Participant receives a £0.15 performance reward and then hits a deliberate error,
        landing on the error page (skipped for bots so that automated tests pass). The extra reward
        makes the errored payout (£0.65) differ from the failed-prescreening payout (£0.50), verifying
        that the screen-out top-up bonus is computed per participant.

The recruiter is selected via the config file rather than in this experiment file:

- ``config.txt`` (default) sets ``recruiter = devprolific``, which simulates the Prolific API
    locally (requests are logged instead of sent, and no credentials or payments are involved), so
    running this directory directly cannot accidentally start paid recruitment.
- ``config.txt.prolific`` sets ``recruiter = prolific`` and is swapped in explicitly for paid test
    deployments with real participants.

How unsuccessful participants (flows 2 and 3) are paid depends on the deployment configuration
(see Exp.config below):

- With screen-out payment enabled (the default; this experiment sets
    `prolific_unsuccessful_base_payment = 0.20`): unsuccessful participants submit their
    study normally (flow 3 via the "Submit to Prolific" button on the error page). Prolific marks them
    as screened out and automatically pays the fixed £0.20, and PsyNet tops them up with a bonus to
    reach their accumulated reward: £0.30 for flow 2 (total £0.50) and £0.45 for flow 3 (total £0.65,
    including the £0.15 performance reward). Requires a workspace with Prolific's custom screening
    feature enabled.
- With `prolific_pay_unsuccessful = false`, the legacy return-for-bonus flows apply: with
    `prolific_enable_return_for_bonus = True`, flow-2 participants are asked to return their
    submission and then receive their accumulated reward as a bonus; with `False`, they are asked
    to return and message the experimenter. Flow-3 participants are asked to message the
    experimenter.

The experimenter should check the following in the Prolific dashboard:
1. Recruitment: Verify that participants are correctly recruited and appear in the Prolific dashboard for the study.
2. Completion Status: Check that participants (ID % 4 == 0 and ID % 4 == 1) who complete the experiment are marked
    as complete in both Prolific and PsyNet.
3. Prescreening Failures: Confirm that participants (ID % 4 == 2) who fail the prescreening are handled appropriately
    (marked as returned or screened-out in both Prolific and PsyNet, depending on the configuration, and paid £0.50 in total).
4. Errors: Confirm that participants (ID % 4 == 3) who hit the error page are handled appropriately
    (with screen-out payment enabled they should be screened out and paid £0.65 in total via the
    error page's "Submit to Prolific" button; the £0.15 performance reward makes this differ from flow 2).
5. Bonus/Reward Payments: For participants (ID % 4 == 0) in the increment performance reward flow, ensure that
    the bonus payment is correctly set in both Prolific and PsyNet.

This test is intended to be deployed and run with real participants.
"""

# pylint: disable=unused-import,abstract-method,unused-argument

import json
import os
import sys

import psynet.experiment
from psynet.page import InfoPage, UnsuccessfulEndPage
from psynet.timeline import CodeBlock, Timeline, join, switch
from psynet.utils import get_logger

# The vendored consents_cococo package (copied from
# https://gitlab.com/computational-audition-lab/cococo-shared) uses absolute
# imports, so the experiment directory must be on sys.path: Dallinger imports
# the experiment as the dallinger_experiment package from a temp copy.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from consents_cococo.consent_cultural_foundation import (  # noqa: E402
    consent_irb_cultural_foundation,
    debrief_page,
)

logger = get_logger()


def normal():
    return join(
        InfoPage(
            "In this simulation, you are a participant who completed the full experiment as expected.",
            time_estimate=1 * 60,
        ),
    )


def failed_prescreening():
    return join(
        InfoPage(
            "In this simulation, you are a participant whose device proved to be incompatible with the experiment requirements.",
            time_estimate=0,
        ),
        UnsuccessfulEndPage(),
    )


class SimulatedExperimentError(Exception):
    """Deliberate error used to test error-page payment handling."""


def _raise_simulated_error(participant):
    from psynet.bot import Bot

    if isinstance(participant, Bot):
        # Automated (bot) test runs should not crash on the simulated error;
        # only real participants exercise the error-page payment flow.
        logger.info("Skipping simulated error for bot participant.")
        return
    raise SimulatedExperimentError(
        "This is a deliberate error raised to test the error page payment flow."
    )


def errored():
    return join(
        InfoPage(
            "In this simulation, you are a participant who is about to experience a technical error. "
            "Please follow the instructions on the next page.",
            time_estimate=0,
        ),
        # Granting a performance reward before the error makes the errored
        # payout (£0.65) differ from the failed-prescreening payout (£0.50),
        # verifying that the screen-out top-up bonus is per participant rather
        # than a flat category amount.
        CodeBlock(lambda participant: participant.inc_performance_reward(0.15)),
        # The reward increment must be committed in an *earlier request* than
        # the error: consecutive CodeBlocks run in the same HTTP request, and
        # the error rolls back that request's database transaction (observed
        # in deployment run 2, where the increment was silently lost). This
        # intermediate page forces a commit between the two code blocks.
        InfoPage(
            "You received a small performance reward of £0.15. "
            "The error will occur when you click Next.",
            time_estimate=0,
        ),
        CodeBlock(_raise_simulated_error),
    )


def normal_plus_performance_reward():
    return join(
        normal(),
        InfoPage(
            "In this simulation you additionally received a small performance reward of £0.10.",
            time_estimate=0,
        ),
        CodeBlock(lambda participant: participant.inc_performance_reward(0.10)),
    )


def get_prolific_settings():
    """Prolific-related settings shared by both recruiters.

    The recruiter itself is set in ``config.txt`` (``devprolific`` by default,
    ``prolific`` in ``config.txt.prolific`` for paid deployments); see the
    module docstring.
    """
    with open("qualification_prolific_en.json", "r") as f:
        qualification = json.dumps(json.load(f))

    return {
        "base_payment": 0.50,
        "prolific_is_custom_screening": False,
        # 2 minutes at a £0.50 reward advertises £15/hr on Prolific (1 minute
        # advertised £30/hr, which was deemed too high for a test study).
        "prolific_estimated_completion_minutes": 2,
        "prolific_recruitment_config": qualification,
        "initial_recruitment_size": 12,
        "auto_recruit": True,
        "currency": "£",
        "wage_per_hour": 10,
    }


class Exp(psynet.experiment.Experiment):
    label = "Simple test experiment"

    config = {
        **get_prolific_settings(),
        "force_incognito_mode": False,
        "title": "Test experiment (Chrome browser, ~1-2 min)",
        "description": "This is a short technical test of our experimental software. While this is not a real experiment, you will be compensated for your time at the regular rate. We appreciate your help in testing our system.",
        "contact_email_on_error": "computational.audition@gmail.com",
        "organization_name": "Max Planck Institute for Empirical Aesthetics",
        "show_reward": False,
        # The experiment should be tested with three configurations (three deployments):
        # 1. prolific_unsuccessful_base_payment = 0.20 (screen-out completion code flow,
        #    on by default; requires a workspace with Prolific's custom screening
        #    feature enabled)
        # 2. prolific_pay_unsuccessful = False, prolific_enable_return_for_bonus = True
        # 3. prolific_pay_unsuccessful = False, prolific_enable_return_for_bonus = False
        "prolific_unsuccessful_base_payment": 0.20,
        # Required for Prolific deployments: caps the number of automatic
        # screen-out payments (worst case spend: slots x 0.20).
        "prolific_screen_out_slots": 120,
        "prolific_enable_return_for_bonus": True,
    }

    timeline = Timeline(
        # DURATION/PAYMENT are passed explicitly because this experiment sets
        # prolific_estimated_completion_minutes and base_payment in Exp.config
        # rather than config.txt, where the consent module would read them.
        consent_irb_cultural_foundation(consent="MAIN", DURATION=2, PAYMENT=0.50),
        InfoPage(
            "What happens next will depend on chance. Either way, you will receive some payment for your time. However, we will be trialling different methods of payment to make sure they are all working properly.",
            # Together with the 1-minute consent page, a participant screened
            # out after this page has accrued 3 minutes, i.e. £0.50 at
            # wage_per_hour = 10.
            time_estimate=2 * 60,
        ),
        switch(
            "participant_flow",
            lambda participant: participant.id % 4,
            {
                0: normal_plus_performance_reward(),
                1: normal(),
                2: failed_prescreening(),
                3: errored(),
            },
        ),
        debrief_page(),
    )
