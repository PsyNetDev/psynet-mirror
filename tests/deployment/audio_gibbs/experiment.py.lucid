"""Lucid variant of the audio Gibbs test experiment.

To use it, copy this file over ``experiment.py`` and ``config.txt.lucid``
over ``config.txt`` (the recruiter settings live in the config file and
``lucid_recruitment_config.json``).
"""

import os
import sys
from typing import List

from markupsafe import Markup

import psynet.experiment
from psynet.asset import LocalStorage
from psynet.bot import Bot
from psynet.consent import LucidConsent
from psynet.demography.general import ExperimentFeedback, HearingLoss
from psynet.page import InfoPage, Page, SuccessfulEndPage
from psynet.prescreen import HugginsHeadphoneTest
from psynet.timeline import Timeline
from psynet.trial.audio_gibbs import (
    AudioGibbsNode,
    AudioGibbsTrial,
    AudioGibbsTrialMaker,
)
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

from . import custom_synth

logger = get_logger()

TARGETS = ["dominant", "trustworthy"]
DIMENSIONS = 7
RANGE = [-800, 800]
GRANULARITY = 25
# Kept deliberately small so a deployment test stays short and cheap.
NUM_ITERATIONS_PER_CHAIN = 2
CHAINS_PER_PARTICIPANT = len(TARGETS)
NUM_TRIALS_PER_PARTICIPANT = NUM_ITERATIONS_PER_CHAIN * CHAINS_PER_PARTICIPANT

# Matches TARGET_N_PARTICIPANTS so the Lucid survey is created with its full
# quota up front: the marketplace UI then shows "Expected Completes = 10" and
# Lucid keeps fielding until 10 completes without PsyNet-side quota top-ups.
INITIAL_RECRUITMENT_SIZE = 10
TARGET_N_PARTICIPANTS = 10


class CulturalFoundationLucidConsent(LucidConsent):
    """Lucid-compatible consent page using the approved CINT consent text."""

    class LucidConsentPage(LucidConsent.LucidConsentPage):
        def __init__(self, time_estimate=60):
            consent = consent_irb_cultural_foundation(
                consent="CINT",
                DURATION=4,
                PAYMENT=0,
            )
            source_page = next(elt for elt in consent.elts if isinstance(elt, Page))
            Page.__init__(
                self,
                label="lucid_consent",
                template_str=source_page.template_str,
                template_arg=source_page.template_arg,
                time_estimate=time_estimate,
                show_early_exit_button=False,
                requires_full_page_reload=True,
            )


class CustomTrial(AudioGibbsTrial):
    snap_slider = True
    autoplay = True
    debug = False
    minimal_time = 3.0
    time_estimate = 7.0

    def get_prompt(self, experiment, participant):
        return Markup(
            "Adjust the slider so that the word sounds as "
            f"<strong>{self.context['target']}</strong> "
            "as possible."
        )


class CustomNode(AudioGibbsNode):
    vector_length = DIMENSIONS
    vector_ranges = [RANGE for _ in range(DIMENSIONS)]
    granularity = GRANULARITY
    # Parallelizes stimulus synthesis across async worker processes.
    n_jobs = 8

    def synth_function(self, vector, output_path, chain_definition):
        custom_synth.synth_stimulus(vector, output_path, chain_definition)


class CustomTrialMaker(AudioGibbsTrialMaker):
    performance_threshold = -1.0
    give_end_feedback_passed = True

    def get_end_feedback_passed_page(self, score):
        score_to_display = "NA" if score is None else f"{(100 * score):.0f}"

        return InfoPage(
            Markup(
                f"Your consistency score was <strong>{score_to_display}&#37;</strong>."
            ),
            time_estimate=5,
        )


trial_maker = CustomTrialMaker(
    id_="audio_gibbs",
    trial_class=CustomTrial,
    node_class=CustomNode,
    chain_type="within",
    expected_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_trials_per_participant=NUM_TRIALS_PER_PARTICIPANT,
    max_nodes_per_chain=NUM_ITERATIONS_PER_CHAIN,
    start_nodes=lambda: [CustomNode(context={"target": target}) for target in TARGETS],
    chains_per_experiment=None,
    trials_per_node=1,
    balance_across_chains=True,
    check_performance_at_end=False,
    check_performance_every_trial=False,
    propagate_failure=False,
    recruit_mode="n_participants",
    target_n_participants=TARGET_N_PARTICIPANTS,
    wait_for_networks=True,
    n_repeat_trials=1,
)


class Exp(psynet.experiment.Experiment):
    label = "Audio game - play with sounds."
    asset_storage = LocalStorage()
    config = {
        "initial_recruitment_size": INITIAL_RECRUITMENT_SIZE,
        "force_incognito_mode": False,
        "title": "Sound game: play with sounds (Chrome browser, Headphones required ~3 min)",
        "description": "A short sound game. Requires a Chrome browser and headphones. The game lasts approximately 3 minutes.",
        "contact_email_on_error": "computational.audition@gmail.com",
        "organization_name": "Max Planck Institute for Empirical Aesthetics",
        "show_reward": False,
        # Lucid's QuotaCPI is derived from estimated_max_reward(wage_per_hour).
        # The default wage of 9/hour yielded a CPI of ~0.5, which converted
        # poorly; doubling the wage roughly doubles the CPI.
        "wage_per_hour": 18,
    }

    timeline = Timeline(
        # Panelists decide within seconds whether to stay; a short plain
        # description up front reduces bounces at entry.
        InfoPage(
            Markup(
                "<h3>4-minute listening study</h3>"
                "<p><strong>Headphones required.</strong> You will make "
                f"{NUM_TRIALS_PER_PARTICIPANT + 1} short sound ratings by "
                "adjusting a slider.</p>"
            ),
            time_estimate=5,
        ),
        CulturalFoundationLucidConsent(time_estimate=60),
        HugginsHeadphoneTest(performance_threshold=0),
        trial_maker,
        HearingLoss(),
        ExperimentFeedback(),
        debrief_page(),
        SuccessfulEndPage(),
    )

    def on_launch(self):
        from dallinger.config import get_config

        recruiter = get_config().get("recruiter")
        if recruiter != "lucid-recruiter":
            raise RuntimeError(
                f"Lucid experiment.py but recruiter={recruiter!r}. "
                "Copy experiment.py.lucid with config.txt.lucid before deploy."
            )
        super().on_launch()

    def recruit(self):
        """Stop Lucid fielding once the participant target is reached.

        PsyNet calls ``recruiter.close_recruitment()`` when no more
        participants are needed, but ``LucidRecruiter.close_recruitment`` is
        a no-op that relies on Lucid stopping at the quota. Lucid does not
        promptly stop admitting entrants at the quota on its own (a fast
        survey ran to 14 completes on a quota of 10 with entrants still
        arriving), so the survey is set to ``complete`` explicitly here.
        """
        super().recruit()
        if not self.need_more_participants:
            self._stop_lucid_fielding()

    def _stop_lucid_fielding(self):
        recruiter = self.recruiter
        if not hasattr(recruiter, "lucidservice"):
            return  # not recruiting via Lucid (e.g. local debug/bot runs)
        try:
            survey_number = recruiter.current_survey_number()
            if survey_number is None:
                return
            service = recruiter.lucidservice
            if service.get_survey_status(survey_number) == "live":
                service.change_status(survey_number, "complete")
                logger.info(
                    "Participant target reached: set Lucid survey %s to complete.",
                    survey_number,
                )
        except Exception:
            logger.warning(
                "Failed to complete the Lucid survey after reaching the "
                "participant target; it may keep fielding.",
                exc_info=True,
            )

    test_n_bots = 2

    def test_bots_ran_successfully(self, bots: List[Bot], **kwargs):
        super().test_bots_ran_successfully(bots, **kwargs)

        for b in bots:
            assert len(b.alive_trials) == NUM_TRIALS_PER_PARTICIPANT
