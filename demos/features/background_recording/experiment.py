"""Optional and required camera recording alongside ordinary button answers.

The two pages deliberately share a label: each clip is keyed by its page UUID.
No page waits for media. Inspect Recording assets in the dashboard afterwards.
"""

import psynet.experiment
from psynet.consent import AudiovisualConsent
from psynet.modular_page import ModularPage, PushButtonControl, VideoRecordConfig
from psynet.page import InfoPage
from psynet.timeline import PageMaker, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


def _choice(prompt, required=False):
    """Build a button page with optional camera capture."""
    return ModularPage(
        "judgment",
        prompt,
        PushButtonControl(["Yes", "No"]),
        time_estimate=5,
        background_recording=VideoRecordConfig(source="camera", required=required),
    )


class JudgmentTrial(StaticTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        """Keep the answer identical under both recording policies."""
        required = self.definition["required"]
        label = "Required" if required else "Optional"
        return _choice(f"{label} trial: choose Yes or No.", required=required)


def _trial_maker(required):
    """Create one trial for each recording policy."""
    return StaticTrialMaker(
        id_="required_recording" if required else "optional_recording",
        trial_class=JudgmentTrial,
        nodes=[StaticNode(definition={"required": required})],
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        target_n_participants=1,
        recruit_mode="n_participants",
    )


class Exp(psynet.experiment.Experiment):
    label = "Background recording policies"
    timeline = Timeline(
        AudiovisualConsent(time_estimate=5),
        _choice("First judgment: choose Yes or No."),
        PageMaker(
            lambda: _choice("Second judgment: choose Yes or No."), time_estimate=5
        ),
        InfoPage(
            "Independent page reached. Your answers are saved; recordings may still be uploading.",
            time_estimate=2,
        ),
        _trial_maker(required=False),
        _trial_maker(required=True),
        InfoPage("Trial comparison complete. Your answers are saved.", time_estimate=2),
    )
