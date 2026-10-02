"""Recording transport fixture for in-place and document-boundary navigation."""

import os

from dallinger import db
from dallinger.experiment import experiment_route
from flask import jsonify

import psynet.experiment
from psynet.db import with_transaction
from psynet.modular_page import ModularPage, VideoPrompt, VideoRecordControl
from psynet.page import InfoPage, wait_for_recording
from psynet.timeline import PageMaker, Timeline, join
from psynet.trial.record import Recording


def _playback(source, dual):
    """Resolve each source independently, retaining clips that did arrive."""
    key = "recording_" + source if dual else "recording"
    return join(
        wait_for_recording(lambda participant: participant.assets[key]),
        PageMaker(
            lambda participant: (
                ModularPage(
                    "playback_" + source,
                    VideoPrompt(
                        participant.assets[key],
                        f"Uploaded {source} clip." if dual else "Uploaded clip.",
                        controls=True,
                        hide_when_finished=False,
                        muted=True,
                    ),
                    time_estimate=3,
                )
                if participant.assets[key].deposited
                else InfoPage(
                    f"{source.capitalize()} recording unavailable. Your answer was saved."
                    if dual
                    else "Recording unavailable. Your answer was saved.",
                    time_estimate=3,
                )
            ),
            time_estimate=3,
        ),
    )


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

    dual = os.environ.get("PSYNET_TEST_RECORDING_DUAL") == "1"

    timeline = Timeline(
        ModularPage(
            "recording",
            "Record a short clip.",
            VideoRecordControl(
                duration=3,
                record_audio=False,
                controls=True,
                show_preview=True,
                recording_source="both" if dual else "camera",
            ),
            time_estimate=3,
            save_answer="recorded_video",
        ),
        InfoPage(
            "Independent page reached.",
            time_estimate=1,
            requires_full_page_reload=os.environ.get("PSYNET_TEST_RECORDING_RELOAD")
            == "1",
        ),
        None
        if os.environ.get("PSYNET_TEST_RECORDING_EXIT") == "1"
        else join(
            _playback("camera", dual),
            _playback("screen", dual) if dual else None,
        ),
    )
