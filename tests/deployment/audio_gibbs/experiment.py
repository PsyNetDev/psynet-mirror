"""Audio Gibbs sampler test experiment.

Participants adjust a slider to make a synthesized word sound as
"dominant" or "trustworthy" as possible. Compared to the sibling
payment-flow test experiment, this one additionally exercises on-the-fly
audio synthesis (parselmouth), asset generation and storage, parallel
async worker processes, and a headphone prescreen.

The recruiter is selected via the config file rather than in this experiment file:

- ``config.txt`` (default) sets ``recruiter = devprolific``, which simulates the Prolific API
    locally (requests are logged instead of sent, and no credentials or payments are involved), so
    running this directory directly cannot accidentally start paid recruitment.
- ``config.txt.prolific`` sets ``recruiter = prolific`` and is swapped in explicitly for paid test
    deployments with real participants.

The Lucid variant still lives in ``experiment.py.lucid`` (with ``config.txt.lucid``) because its
timeline and Experiment class genuinely differ (LucidConsent, a welcome page, and a ``recruit()``
override). ``on_launch`` aborts unless the configured recruiter is ``prolific`` or
``devprolific``, so a Lucid config cannot start a paid survey with this timeline.
"""

import json
import os
import sys
from typing import List

from markupsafe import Markup

import psynet.experiment
from psynet.asset import LocalStorage
from psynet.bot import Bot
from psynet.demography.general import ExperimentFeedback, HearingLoss
from psynet.page import InfoPage, SuccessfulEndPage
from psynet.prescreen import HugginsHeadphoneTest
from psynet.timeline import Timeline
from psynet.trial.audio_gibbs import (
    AudioGibbsNode,
    AudioGibbsTrial,
    AudioGibbsTrialMaker,
)

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

TARGETS = ["dominant", "trustworthy"]
DIMENSIONS = 7
RANGE = [-800, 800]
GRANULARITY = 25
# Kept deliberately small so a deployment test stays short and cheap.
NUM_ITERATIONS_PER_CHAIN = 2
CHAINS_PER_PARTICIPANT = len(TARGETS)
NUM_TRIALS_PER_PARTICIPANT = NUM_ITERATIONS_PER_CHAIN * CHAINS_PER_PARTICIPANT

INITIAL_RECRUITMENT_SIZE = 3
TARGET_N_PARTICIPANTS = 5


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
        "prolific_estimated_completion_minutes": 3,
        "prolific_recruitment_config": qualification,
        # True so deployment tests exercise the programmatic top-up path
        # (ProlificRecruiter.recruit); recruitment grows from
        # INITIAL_RECRUITMENT_SIZE toward TARGET_N_PARTICIPANTS.
        "auto_recruit": True,
        "currency": "£",
        "wage_per_hour": 10,
    }


class Exp(psynet.experiment.Experiment):
    label = "Audio game - play with sounds."
    asset_storage = LocalStorage()
    config = {
        **get_prolific_settings(),
        "initial_recruitment_size": INITIAL_RECRUITMENT_SIZE,
        # Required for Prolific deployments: caps the number of automatic
        # screen-out payments (see prolific_pay_unsuccessful).
        "prolific_screen_out_slots": 10 * INITIAL_RECRUITMENT_SIZE,
        "force_incognito_mode": False,
        "title": "Sound game: play with sounds (Chrome browser, Headphones required ~3 min)",
        "description": "A short sound game. Requires a Chrome browser and headphones. The game lasts approximately 3 minutes.",
        "contact_email_on_error": "computational.audition@gmail.com",
        "organization_name": "Max Planck Institute for Empirical Aesthetics",
        "show_reward": False,
    }

    def on_launch(self):
        from dallinger.config import get_config

        recruiter = get_config().get("recruiter")
        if recruiter not in ("prolific", "devprolific"):
            raise RuntimeError(
                f"Prolific experiment.py but recruiter={recruiter!r}. "
                "For Lucid, copy experiment.py.lucid with config.txt.lucid."
            )
        super().on_launch()

    timeline = Timeline(
        # DURATION/PAYMENT are passed explicitly because this experiment sets
        # prolific_estimated_completion_minutes and base_payment in Exp.config
        # rather than config.txt, where the consent module would read them.
        consent_irb_cultural_foundation(consent="MAIN", DURATION=3, PAYMENT=0.50),
        HugginsHeadphoneTest(performance_threshold=0),
        trial_maker,
        HearingLoss(),
        ExperimentFeedback(),
        debrief_page(),
        SuccessfulEndPage(),
    )

    test_n_bots = 2

    def test_bots_ran_successfully(self, bots: List[Bot], **kwargs):
        super().test_bots_ran_successfully(bots, **kwargs)

        for b in bots:
            assert len(b.alive_trials) == NUM_TRIALS_PER_PARTICIPANT
