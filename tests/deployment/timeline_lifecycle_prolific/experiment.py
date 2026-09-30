"""Prolific deployment test for PsyNet 14's in-place timeline transitions.

PsyNet 14 swaps most timeline pages into the open browser document instead of
reloading it. Earlier deployment tests only show that participants got
through; they cannot tell an in-place transition from a reload, or notice
state leaking from one page to the next. This experiment records that
evidence from real browsers and devices, cheaply: eight participants, about
three minutes each, no performance bonus.

Every probed page loads ``static/lifecycle-document.js`` through
``js_dependencies`` (once per document) and ``static/lifecycle-probe.js``
through ``js_page_modules`` (once per page). The probe submits a record as
``metadata.lifecycle`` on the page's response: a per-document ID, how often
the dependency and the page module ran, whether page-scoped CSS and
``psynet.var`` values are the current page's, how many sounds are playing,
whether the participant clicked or typed before the page was submitted, how
long the transition into the page took, and the result of
``psynetLayout.collectViolations()``.

The timeline mixes transitions that must keep the document with ones that
must replace it, so the reload cases double as positive controls for the
detection:

- ``lt_intro`` to ``lt_after_wait``: in place, across a custom component that
  contributes CSS and JS variables, a radio question, and an
  ``AsyncCodeBlock(wait=True)`` hold.
- ``lt_audio`` to ``lt_after_audio``: in place; looping audio on ``lt_audio``
  must stop before the next page activates.
- ``lt_auto_advance`` (a ``WaitPage``) to ``lt_after_auto``: in place; the
  wait timer must submit once and must not submit the next page.
- ``lt_reload``: Next appears only after the participant reloads the page, so
  its response comes from a page ``/timeline`` rebuilt in a new document.
- ``lt_full_reload`` (``requires_full_page_reload=True``) and the jsPsych page
  each get a new document on entry and on exit.
- ``lt_after_jspsych`` to ``lt_final``: in place again after the reloads.
- Participants with ``id % 8 == 3`` are asked to press Leave, which exercises
  Prolific's screen-out early exit.

A code block also saves a small participant asset, so the export shows
content-addressed asset storage on a real deployment. ``on_launch`` refuses
to start if ``local_only/``, which ``deploy.toml`` excludes, reached the
running experiment.

``analyze.py`` reads a ``psynet export`` directory and prints one PASS/FAIL
line per check. Bots do not run JavaScript, so a ``psynet test local`` export
contains no lifecycle records; walk the experiment in a local Chrome under
``psynet debug local`` to check the analysis before a paid run.

On a paid run:

1. Deploy with ``config.txt.prolific`` copied to ``config.txt``.
2. Wait until the study's eight places are used up and the participant who
   was asked to press Leave (``id % 8 == 3``) has submitted.
3. Run ``psynet export ssh`` and then ``python analyze.py <export-dir>``.
4. Compare Prolific's submission statuses and payments with the
   ``participant statuses`` line: completed participants are approved, and
   the Leave participant is screened out with a top-up bonus.

The recruiter is selected via the config file rather than in this experiment
file:

- ``config.txt`` (default) sets ``recruiter = devprolific``, which simulates
  the Prolific API locally so running this directory cannot accidentally
  start paid recruitment.
- ``config.txt.prolific`` sets ``recruiter = prolific``; copy it to
  ``config.txt`` immediately before a paid ``psynet deploy ssh``.
"""

import json
import os
import sys
import tempfile
import time
from typing import List

from markupsafe import Markup

import psynet.experiment
from psynet.asset import asset
from psynet.bot import Bot
from psynet.modular_page import (
    AudioPrompt,
    ModularPage,
    Prompt,
    PushButtonControl,
    RadioButtonControl,
)
from psynet.page import InfoPage, JsPsychPage, SuccessfulEndPage, WaitPage
from psynet.timeline import AsyncCodeBlock, CodeBlock, Timeline, conditional

# The vendored consents_cococo package (copied from
# https://gitlab.com/computational-audition-lab/cococo-shared) uses absolute
# imports, so the experiment directory must be on sys.path: Dallinger imports
# the experiment as the dallinger_experiment package from a temp copy.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from consents_cococo.consent_cultural_foundation import (  # noqa: E402
    consent_irb_cultural_foundation,
)

DOCUMENT_MARKER = "/static/lifecycle-document.js"
PROBE_MODULE = "/static/lifecycle-probe.js"
RELOAD_MODULE = "/static/reload-step.js"
COMPONENT_TOKEN = "component-js-vars-ok"
EXCLUSION_MARKER = os.path.join("local_only", "deploy-exclusion-marker.txt")
LEAVE_EVERY = 8
LEAVE_REMAINDER = 3
ESTIMATED_MINUTES = 3
BASE_PAYMENT = 0.50

JSPSYCH_DEPENDENCIES = [
    "/static/jspsych/jspsych.js",
    "/static/jspsych/plugin-html-keyboard-response.js",
    DOCUMENT_MARKER,
]


def _probe_assets(step, extra_modules=()):
    """Page arguments that attach the lifecycle probe to a page."""
    return {
        "js_dependencies": [DOCUMENT_MARKER],
        "js_page_modules": [PROBE_MODULE, *extra_modules],
        "js_vars": {"lifecycle_step": step},
    }


def probed_page(
    label, prompt, control=None, time_estimate=8, extra_modules=(), **kwargs
):
    """A ModularPage whose response carries a lifecycle record."""
    return ModularPage(
        label,
        prompt,
        control,
        time_estimate=time_estimate,
        **_probe_assets(label, extra_modules),
        **kwargs,
    )


def continue_button():
    return PushButtonControl(["Continue"])


class LifecycleComponentPrompt(Prompt):
    """Prompt that contributes page CSS and JS variables through component hooks."""

    def __init__(self):
        super().__init__(
            Markup(
                '<div class="lifecycle-card"><p>This box is styled by a '
                "stylesheet that belongs to this page only.</p></div>"
            )
        )

    def get_css_links(self):
        return ["/static/lifecycle-page.css"]

    def get_js_vars(self):
        return {"lifecycle_component_token": COMPONENT_TOKEN}


def _hold_briefly(participant):
    time.sleep(4)
    participant.var.lifecycle_async_finished = True


def _save_summary_asset(participant):
    summary = {
        "participant_id": participant.id,
        "device": participant.var.lifecycle_device,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json") as file:
        json.dump(summary, file)
        file.flush()
        asset(
            file.name,
            local_key="lifecycle_summary",
            extension=".json",
            description="Small per-participant summary for the export check",
            parent=participant,
        ).deposit()


def _asked_to_leave(participant):
    return participant.id % LEAVE_EVERY == LEAVE_REMAINDER


leave_request = probed_page(
    "lt_leave_request",
    Markup(
        "<p>This participant is asked to test the <strong>Leave</strong> "
        "button. Please press <strong>Leave</strong> at the bottom of the "
        "page and confirm. You will still be paid as described.</p>"
        "<p>If you cannot find the button, press Next instead.</p>"
    ),
    show_early_exit_button=True,
)


def get_prolific_settings():
    """Return settings shared by real and simulated Prolific recruitment."""
    with open("qualification_prolific_en.json", "r") as file:
        qualification = json.dumps(json.load(file))

    return {
        "auto_recruit": True,
        "base_payment": BASE_PAYMENT,
        "currency": "£",
        "initial_recruitment_size": 8,
        "prolific_estimated_completion_minutes": ESTIMATED_MINUTES,
        "prolific_is_custom_screening": False,
        "prolific_recruitment_config": qualification,
        "prolific_screen_out_slots": 4,
        "prolific_unsuccessful_base_payment": 0.20,
        "wage_per_hour": 10,
    }


class Exp(psynet.experiment.Experiment):
    """Short experiment that records in-place transition evidence from real browsers."""

    label = "Timeline lifecycle deployment test"

    config = {
        **get_prolific_settings(),
        "contact_email_on_error": "computational.audition@gmail.com",
        "description": (
            "A short paid technical test of our experiment software. "
            "It takes about three minutes and works on computers and phones."
        ),
        "force_incognito_mode": False,
        "organization_name": "Max Planck Institute for Empirical Aesthetics",
        "show_reward": False,
        "title": "Short technical test (Chrome, about 3 minutes)",
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
        if os.path.exists(EXCLUSION_MARKER):
            raise RuntimeError(
                f"{EXCLUSION_MARKER} was deployed although deploy.toml excludes "
                "local_only/."
            )
        super().on_launch()

    timeline = Timeline(
        # DURATION/PAYMENT are passed explicitly because this experiment sets
        # prolific_estimated_completion_minutes and base_payment in Exp.config
        # rather than config.txt, where the consent module would read them.
        consent_irb_cultural_foundation(
            consent="MAIN", DURATION=ESTIMATED_MINUTES, PAYMENT=BASE_PAYMENT
        ),
        probed_page(
            "lt_intro",
            "This is a short technical test of our experiment software, not a "
            "scientific study. Please follow the instructions on each page.",
        ),
        probed_page(
            "lt_component",
            LifecycleComponentPrompt(),
            continue_button(),
            bot_response="Continue",
        ),
        probed_page(
            "lt_choices",
            "Which kind of device are you using?",
            RadioButtonControl(["Computer", "Phone", "Tablet"]),
            save_answer="lifecycle_device",
            bot_response="Computer",
        ),
        AsyncCodeBlock(
            _hold_briefly,
            expected_wait=4,
            content="Please wait a few seconds.",
        ),
        probed_page("lt_after_wait", "Thank you for waiting."),
        probed_page(
            "lt_audio",
            AudioPrompt(
                # Long enough to still be playing when most participants press
                # Continue; a very short looped clip restarts the trial many
                # times a second and floods the event log.
                "/static/tone.wav",
                "You may hear a soft tone. Press Continue at any time.",
                loop=True,
            ),
            continue_button(),
            bot_response="Continue",
        ),
        probed_page("lt_after_audio", "The sound should have stopped now."),
        WaitPage(
            wait_time=2,
            content="This screen continues automatically.",
            **_probe_assets("lt_auto_advance"),
        ),
        probed_page("lt_after_auto", "The automatic screen has finished."),
        probed_page(
            "lt_reload",
            Markup(
                "<p>Please reload this page using the button below. "
                "Next appears after the page has reloaded.</p>"
                '<button type="button" id="lifecycle-reload" '
                'class="btn btn-outline-primary">Reload this page</button>'
                '<p id="lifecycle-reload-done" style="display: none">'
                "Thank you, the page has reloaded.</p>"
            ),
            extra_modules=[RELOAD_MODULE],
        ),
        probed_page(
            "lt_full_reload",
            "This page is loaded in a different way from the previous pages.",
            requires_full_page_reload=True,
        ),
        probed_page("lt_after_full_reload", "Next comes a short automatic screen."),
        CodeBlock(_save_summary_asset),
        JsPsychPage(
            "lt_jspsych",
            timeline="/static/jspsych-check.js",
            time_estimate=5,
            js_dependencies=JSPSYCH_DEPENDENCIES,
            css_links=["/static/jspsych/jspsych.css"],
            bot_response=None,
        ),
        probed_page("lt_after_jspsych", "The automatic screen has finished."),
        conditional("lt_leave_branch", _asked_to_leave, leave_request),
        probed_page("lt_final", "That was the last test page."),
        InfoPage(
            "Thank you. This was a short technical test of our experiment "
            "software, not a scientific study. Your responses will not be used "
            "as research data. Questions: computational.audition@gmail.com.",
            time_estimate=10,
        ),
        SuccessfulEndPage(),
    )

    test_n_bots = 3

    def test_check_bot(self, bot: Bot, **kwargs):
        """Check the server-side effects that bots can reach."""
        from psynet.asset import Asset

        super().test_check_bot(bot, **kwargs)
        assert bot.var.lifecycle_async_finished
        assert bot.var.lifecycle_device == "Computer"
        assert (
            Asset.query.filter_by(
                participant_id=bot.id, local_key="lifecycle_summary"
            ).count()
            == 1
        )

    def test_bots_ran_successfully(self, bots: List[Bot], **kwargs):
        """Confirm that one bot took the Leave branch and pressed Next."""
        super().test_bots_ran_successfully(bots, **kwargs)
        leave_answers = [
            bot for bot in bots if _asked_to_leave(bot) and not bot.early_exited
        ]
        assert len(leave_answers) == 1
