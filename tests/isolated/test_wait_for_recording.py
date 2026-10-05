"""Exercise non-trial recording waits through real timeline navigation."""

from datetime import timedelta

import pytest
from dallinger import db
from test_media_upload import pytestmark as pytestmark
from test_media_upload import reservation as reservation
from timeline_hold_helpers import _process_response

from psynet import media_upload
from psynet.experiment import get_experiment
from psynet.page import InfoPage, wait_for_recording
from psynet.participant import Participant
from psynet.timeline import PageMaker, Timeline
from psynet.timeline_hold import _ConditionHoldPage


@pytest.mark.parametrize("outcome", ["expired", "deposited", "stalled", "legacy"])
def test_recording_wait_preserves_participant(reservation, monkeypatch, outcome):
    asset, _ = reservation
    participant = asset.participant
    participant_id = participant.id
    now = media_upload._utcnow()
    deadline = asset.upload_deadline
    if outcome == "legacy":
        asset.upload_status = None
    monkeypatch.setattr(media_upload, "_utcnow", lambda: now)
    monkeypatch.setattr("psynet.timeline_hold.timenow", lambda: now)
    timeline = Timeline(
        wait_for_recording(lambda participant: participant.assets["video"]),
        PageMaker(
            lambda participant: InfoPage(
                "Playback" if participant.assets["video"].deposited else "Unavailable",
                time_estimate=0,
            ),
            time_estimate=0,
        ),
    )
    exp = get_experiment()
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    assert isinstance(timeline.get_current_elt(exp, participant), _ConditionHoldPage)
    if outcome != "legacy":
        now += timedelta(seconds=30)
        _process_response(
            exp, participant, participant.page_uuid, timeline_hold_resume=True
        )
        assert isinstance(
            timeline.get_current_elt(exp, participant), _ConditionHoldPage
        )
    if outcome == "expired":
        db.session.commit()
        now = deadline + timedelta(seconds=1)
        media_upload._expire_recordings()
        participant = db.session.get(Participant, participant_id)
        assert participant.assets["video"].upload_status == "expired"
    elif outcome == "deposited":
        asset.deposited = True
        asset.upload_status = "deposited"
    elif outcome == "legacy":
        now += timedelta(seconds=21)
    else:
        now = deadline + timedelta(seconds=41)
    _process_response(
        exp, participant, participant.page_uuid, timeline_hold_resume=True
    )
    assert timeline.get_current_elt(exp, participant).content == (
        "Playback" if outcome == "deposited" else "Unavailable"
    )
    assert not participant.failed
    assert participant.assets["video"].upload_deadline == deadline
