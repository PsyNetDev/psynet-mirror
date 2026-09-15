"""Minimal Prolific deployment test for sequential automatic recruitment.

The study opens with one Prolific place. Each successful completion causes
PsyNet's ``n_participants`` recruitment criterion to request one more place,
until ten participants have completed the experiment. This deliberately
tests nine sequential calls to Prolific's incremental recruitment API.

Copy ``config.txt.devprolific`` to ``config.txt`` for safe local testing.
Copy ``config.txt.prolific`` instead before a paid deployment.
"""

import json
import os
import sys
from typing import List

import psynet.experiment
from psynet.bot import Bot
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage, SuccessfulEndPage
from psynet.timeline import Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

# The vendored consents_cococo package (copied from
# https://gitlab.com/computational-audition-lab/cococo-shared) uses absolute
# imports, so the experiment directory must be on sys.path: Dallinger imports
# the experiment as the dallinger_experiment package from a temp copy.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from consents_cococo.consent_cultural_foundation import (  # noqa: E402
    consent_irb_cultural_foundation,
    debrief_page,
)

INITIAL_RECRUITMENT_SIZE = 1
TARGET_N_PARTICIPANTS = 10


class AutoRecruitTrial(StaticTrial):
    """A single short trial that confirms the participant can submit data."""

    time_estimate = 5

    def show_trial(self, experiment, participant):
        return ModularPage(
            "auto_recruit_check",
            "Please select the button below to complete the test task.",
            PushButtonControl(["Complete test"]),
            time_estimate=self.time_estimate,
            bot_response="Complete test",
        )


trial_maker = StaticTrialMaker(
    id_="auto_recruit",
    trial_class=AutoRecruitTrial,
    nodes=[StaticNode(definition={"test": "prolific_auto_recruit"})],
    expected_trials_per_participant=1,
    max_trials_per_participant=1,
    recruit_mode="n_participants",
    target_n_participants=TARGET_N_PARTICIPANTS,
)


def get_prolific_settings():
    """Return settings shared by real and simulated Prolific recruitment."""
    with open("qualification_prolific_en.json", "r") as file:
        qualification = json.dumps(json.load(file))

    return {
        "auto_recruit": True,
        "base_payment": 0.50,
        "currency": "£",
        "initial_recruitment_size": INITIAL_RECRUITMENT_SIZE,
        "prolific_estimated_completion_minutes": 2,
        "prolific_is_custom_screening": False,
        "prolific_recruitment_config": qualification,
        "prolific_screen_out_slots": 10,
        "wage_per_hour": 15,
    }


class Exp(psynet.experiment.Experiment):
    """Short experiment that exercises Prolific automatic place top-ups."""

    label = "Prolific auto-recruit deployment test"

    config = {
        **get_prolific_settings(),
        "contact_email_on_error": "computational.audition@gmail.com",
        "description": (
            "A short paid technical test of participant recruitment. "
            "The task takes approximately one to two minutes."
        ),
        "force_incognito_mode": False,
        "organization_name": "Max Planck Institute for Empirical Aesthetics",
        "show_reward": False,
        "title": "Short technical test (Chrome, about 1-2 minutes)",
    }

    def on_launch(self):
        """Refuse deployment through an unrelated recruiter."""
        from dallinger.config import get_config

        recruiter = get_config().get("recruiter")
        if recruiter not in ("prolific", "devprolific"):
            raise RuntimeError(
                "This deployment test requires recruiter=prolific or devprolific, "
                f"not {recruiter!r}."
            )
        super().on_launch()

    timeline = Timeline(
        # DURATION/PAYMENT are passed explicitly because this experiment sets
        # prolific_estimated_completion_minutes and base_payment in Exp.config
        # rather than config.txt, where the consent module would read them.
        consent_irb_cultural_foundation(consent="MAIN", DURATION=2, PAYMENT=0.50),
        InfoPage(
            "This is a short technical test. You will answer one simple question.",
            time_estimate=5,
        ),
        trial_maker,
        InfoPage(
            "Thank you. Your response was recorded successfully.",
            time_estimate=5,
        ),
        debrief_page(),
        SuccessfulEndPage(),
    )

    test_n_bots = 1

    def test_bots_ran_successfully(self, bots: List[Bot], **kwargs):
        """Confirm that the local test reaches and completes the static trial."""
        super().test_bots_ran_successfully(bots, **kwargs)
        assert len(bots[0].alive_trials) == 1
