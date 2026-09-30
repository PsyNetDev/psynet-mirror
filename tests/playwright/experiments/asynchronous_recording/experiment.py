"""Private recording transport fixture; production controls remain disabled."""

import os

import psynet.experiment
from dallinger import db
from dallinger.experiment import experiment_route
from flask import jsonify
from psynet.db import with_transaction
from psynet.modular_page import ModularPage, VideoPrompt, VideoRecordControl
from psynet.page import InfoPage, wait_for_recording
from psynet.timeline import PageMaker, Timeline, join
from psynet.trial.record import Recording


class AsyncVideoControl(VideoRecordControl):
    _async_upload = True


class Exp(psynet.experiment.Experiment):
    label = "Asynchronous recording test"

    @experiment_route("/test-recording-state/<int:recording_id>", methods=["GET"])
    @staticmethod
    @with_transaction
    def recording_state(recording_id):
        """Expose durable lifecycle evidence only in this private test fixture."""
        asset = db.session.get(Recording, recording_id)
        return jsonify(
            status=asset.upload_status,
            deadline=asset.upload_deadline.isoformat(),
            received=asset.upload_received_at is not None,
            deposited=asset.deposited,
            participant_failed=asset.participant.failed,
            trial_id=asset.trial_id,
        )

    timeline = Timeline(
        ModularPage(
            "recording",
            "Record a short clip.",
            AsyncVideoControl(
                duration=3, record_audio=False, controls=True, show_preview=True
            ),
            time_estimate=3,
            save_answer="recorded_video",
        ),
        InfoPage("Independent page reached.", time_estimate=1),
        None if os.environ.get("PSYNET_TEST_RECORDING_EXIT") == "1" else join(
            wait_for_recording(lambda participant: participant.assets["recording"]),
            PageMaker(
                lambda participant: ModularPage(
                    "playback",
                    VideoPrompt(
                        participant.var.recorded_video["camera_url"],
                        "Uploaded clip.",
                        controls=True,
                        hide_when_finished=False,
                        muted=True,
                    ),
                    time_estimate=3,
                )
                if participant.assets["recording"].deposited
                else InfoPage(
                    "Recording unavailable. Your answer was saved.", time_estimate=3
                ),
                time_estimate=3,
            ),
        ),
    )
