"""Exercise real upload expiry, chain exclusion, playback, and performance checks."""

import shutil
from pathlib import Path

import psynet.experiment
from psynet.modular_page import ModularPage, VideoPrompt, VideoRecordControl
from psynet.page import InfoPage
from psynet.timeline import CodeBlock, Timeline, join
from psynet.trial.video import (
    CameraImitationChainNode,
    CameraImitationChainTrial,
    CameraImitationChainTrialMaker,
)


class AsyncControl(VideoRecordControl):
    _async_upload = True


class VideoTrial(CameraImitationChainTrial):
    time_estimate = 3

    def show_trial(self, experiment, participant):
        """Record seeds directly and play the parent clip before imitation."""
        recording = ModularPage(
            "recording", "Record the gesture.",
            AsyncControl(duration=2, record_audio=False, show_preview=True, controls=True),
            time_estimate=2,
        )
        if self.degree == 0:
            return recording
        return join(
            ModularPage("watch", VideoPrompt(self.assets["stimulus"], "Watch the previous recording.", muted=True), time_estimate=1),
            recording,
        )

    def analyze_recording(self, audio_file, output_plot):
        """Accept any successfully deposited test clip."""
        return {"failed": False, "no_plot_generated": True}

    def show_feedback(self, experiment, participant):
        """Provide a stable checkpoint after successful analysis."""
        return InfoPage("Recording accepted.", time_estimate=1)


class VideoNode(CameraImitationChainNode):
    def create_initial_seed(self, experiment, participant):
        """Use the same deterministic seed in both chains."""
        return "gesture"

    def synthesize_target(self, output_file):
        """Use a fixture seed, then only deposited parent recordings."""
        if self.degree == 0:
            source = Path(psynet.__file__).resolve().parents[1] / "demos/experiments/imitation_chain_video/assets/example_recording.webm"
            shutil.copyfile(source, output_file)
        else:
            self.parent.alive_trials[0].recording.export(output_file)


class VideoTrialMaker(CameraImitationChainTrialMaker):
    performance_check_type = "performance"
    performance_threshold = 0.5

    def performance_check(self, experiment, participant, participant_trials):
        """Verify persisted outcomes while retaining the normal score policy."""
        result = super().performance_check(experiment, participant, participant_trials)
        trials = sorted(participant_trials, key=lambda trial: trial.id)
        assert len(trials) == 3
        failed, seed, imitation = trials
        assert failed.failed_reason == "recording_upload_timeout"
        assert failed.recording.upload_status == "expired"
        assert not failed.async_post_trial_requested
        assert failed.network_id != seed.network_id == imitation.network_id
        assert (seed.degree, imitation.degree) == (0, 1)
        assert seed.finalized and imitation.finalized
        assert seed.recording.deposited and imitation.recording.deposited
        assert result["passed"] and abs(result["score"] - 2 / 3) < 1e-8
        participant.var.set("chain_checks_passed", True)
        return result


def _assert_complete(participant):
    """Ensure the final page cannot bypass the performance assertions."""
    assert participant.var.chain_checks_passed
    assert not participant.failed


class Exp(psynet.experiment.Experiment):
    label = "Missing chain recording"
    timeline = Timeline(
        VideoTrialMaker(
            id_="video-chain", trial_class=VideoTrial, node_class=VideoNode,
            chain_type="within", expected_trials_per_participant=4,
            max_nodes_per_chain=2, chains_per_participant=2, trials_per_node=1,
            target_n_participants=1, check_performance_at_end=True,
            propagate_failure=False, wait_for_networks=False,
        ),
        CodeBlock(_assert_complete),
        InfoPage("Chain checks passed.", time_estimate=1),
    )
