"""Accepted video answers reserve uploads before the next page is consumed."""

import uuid

import pytest
from dallinger import db

from psynet.asset import LocalStorage
from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage, VideoRecordControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Response, Timeline
from psynet.trial.record import Recording

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


@pytest.fixture
def submission(db_session, monkeypatch, tmp_path):
    exp = get_experiment()
    monkeypatch.setenv("PASSTHROUGH_ERRORS", "1")
    monkeypatch.setattr(exp.assets, "storage", LocalStorage(str(tmp_path)))
    participant = Participant(
        experiment=exp,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    db.session.flush()
    control = VideoRecordControl(duration=5, recording_source="both")
    control._async_upload = True
    page = ModularPage("video", "Record", control, time_estimate=5)
    timeline = Timeline(page, InfoPage("Continue", time_estimate=1))
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    db.session.commit()

    def submit(sizes=None, unavailable=None):
        return exp.process_response(
            participant_id=participant.id,
            raw_answer=None,
            blobs={},
            metadata={
                "time_taken": 5,
                "recording_upload_unavailable": unavailable or {},
                "recording_uploads": sizes
                if sizes is not None
                else {"camera": 5 * 1024**2, "screen": 5 * 1024**2},
            },
            page_uuid=participant.page_uuid,
            client_ip_address="127.0.0.1",
            include_timeline_fragment=False,
        ).get_json()

    return exp, participant, page, submit


def test_accepted_video_reserves_both_sources_before_advancing(submission):
    from psynet.media_upload import _utcnow

    exp, participant, page, submit = submission
    original_page = participant.page_uuid
    before = _utcnow()
    result = submit()
    assert result["submission"] == "approved"
    assert exp.timeline.get_current_elt(exp, participant).content == "Continue"
    response = Response.query.filter_by(participant_id=participant.id).one()
    assert response.successful_validation
    assert response.answer == participant.answer
    assert {item["source"] for item in result["recording_uploads"]} == {
        "camera",
        "screen",
    }
    for source in ("camera", "screen"):
        asset = db.session.get(Recording, response.answer[f"{source}_id"])
        assert asset.upload_context["page_uuid"] == original_page
        assert asset.upload_context["response_id"] == response.id
        assert asset.participant_id == participant.id
        assert asset.upload_status == "pending" and not asset.deposited
        assert response.answer[f"{source}_url"] == asset.url
        # Both sources share bandwidth: 10 MiB, not 5 MiB, determines the allowance.
        assert 196 <= (asset.upload_deadline - before).total_seconds() <= 200


@pytest.mark.parametrize("unavailable", [{}, {"camera": "queue_full"}])
def test_rejected_video_creates_no_reservations_and_can_be_resubmitted(
    submission, monkeypatch, unavailable
):
    exp, participant, page, submit = submission
    original_page = participant.page_uuid
    participant.answer = "Earlier answer"
    validate = page.validate
    monkeypatch.setattr(page, "validate", lambda **kwargs: "Please try again")
    assert submit(unavailable=unavailable)["submission"] == "rejected"
    assert Recording.query.count() == 0
    assert participant.page_uuid == original_page
    assert participant.answer == "Earlier answer"
    monkeypatch.setattr(page, "validate", validate)
    assert submit()["submission"] == "approved"
    assert Recording.query.count() == 2


@pytest.mark.parametrize(
    "sizes",
    [
        {"camera": 10},
        {"camera": 10, "screen": -1},
        {"camera": True, "screen": 10},
        {"camera": "large", "screen": 10},
    ],
)
def test_invalid_source_manifest_cannot_reserve_recordings(submission, sizes):
    _, _, _, submit = submission
    with pytest.raises(ValueError, match="Recording sizes|every expected"):
        submit(sizes)
    assert Recording.query.count() == 0


def test_final_references_are_saved_once_in_accumulators_and_variables(submission):
    _, participant, page, submit = submission
    page.save_answer = "saved_recording"
    participant.answer_accumulators = [{}]
    db.session.commit()
    assert submit()["submission"] == "approved"
    db.session.commit()
    db.session.expire_all()
    response = Response.query.filter_by(participant_id=participant.id).one()
    assert participant.answer_accumulators == [{"video": response.answer}]
    assert participant.var.saved_recording == response.answer
    assert response.answer["camera_id"] is not None


def test_navigation_failure_rolls_back_upload_reservations(submission, monkeypatch):
    exp, participant, _, submit = submission
    original_page = participant.page_uuid

    def fail_navigation(*args):
        raise RuntimeError("Navigation failed")

    monkeypatch.setattr(exp.timeline, "advance_page", fail_navigation)
    with pytest.raises(RuntimeError, match="Navigation failed"):
        submit()
    db.session.rollback()
    assert Recording.query.count() == 0
    assert Response.query.count() == 0
    assert participant.page_uuid == original_page


def test_completion_hook_sees_final_references_and_custom_answer_fields(
    submission, monkeypatch
):
    _, participant, page, submit = submission
    observed = []

    def validate(response, **kwargs):
        response.answer = {**response.answer, "custom_field": "retained"}

    monkeypatch.setattr(page, "validate", validate)
    monkeypatch.setattr(
        page,
        "on_complete",
        lambda experiment, participant: observed.append(dict(participant.answer)),
    )
    assert submit()["submission"] == "approved"
    assert observed == [participant.answer]
    assert observed[0]["camera_id"] is not None
    assert observed[0]["custom_field"] == "retained"


def test_recordings_keep_the_original_trial_when_completion_moves_the_cursor(
    submission, monkeypatch
):
    from psynet.trial.main import GenericTrialNode, Trial

    exp, participant, page, submit = submission
    node = GenericTrialNode("recording_submission", exp)
    trial = Trial(
        experiment=exp,
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
        definition={},
    )
    db.session.add(trial)
    db.session.flush()
    participant.current_trial = trial
    db.session.commit()
    monkeypatch.setattr(
        page,
        "on_complete",
        lambda experiment, participant: setattr(participant, "current_trial", None),
    )
    assert submit()["submission"] == "approved"
    assert participant.current_trial is None
    assert {asset.trial_id for asset in Recording.query.all()} == {trial.id}
    assert {asset.upload_context["response_id"] for asset in Recording.query.all()} == {
        trial.response_id
    }


@pytest.mark.parametrize(
    "size, unavailable, reason",
    [
        (128 * 1024**2 + 1, {}, "size_limit"),
        (0, {}, "missing_recording"),
        (10, {"camera": "queue_full"}, "queue_full"),
        (10, {"camera": "transport_unavailable"}, "transport_unavailable"),
    ],
)
def test_unavailable_recording_fails_only_its_trial_at_deadline(
    submission, monkeypatch, size, unavailable, reason
):
    from datetime import timedelta

    from psynet import media_upload
    from psynet.trial.main import GenericTrialNode, Trial

    exp, participant, _, submit = submission
    monkeypatch.delenv("PASSTHROUGH_ERRORS")
    monkeypatch.setattr(type(exp), "report_error", lambda *args, **kwargs: None)
    trial = Trial(
        experiment=exp,
        node=GenericTrialNode("recording_submission", exp),
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
        definition={},
    )
    db.session.add(trial)
    db.session.flush()
    participant.current_trial = trial
    db.session.commit()
    participant_id, trial_id = participant.id, trial.id
    result = submit({"camera": size, "screen": 10}, unavailable)
    assert result["submission"] == "approved"
    assert {slot["source"] for slot in result["recording_uploads"]} == {"screen"}
    camera = Recording.query.filter_by(local_key="video_camera").one()
    assert camera.upload_token_hash is None
    assert not camera.deposited
    assert camera.upload_context["unavailable_reason"] == reason
    assert camera.upload_context["captured_size_bytes"] == size
    assert not trial.failed and not participant.failed
    camera_id = camera.id
    deadline = camera.upload_deadline
    db.session.commit()
    monkeypatch.setattr(
        media_upload, "_utcnow", lambda: deadline - timedelta(seconds=1)
    )
    media_upload._expire_recordings()
    assert not db.session.get(Trial, trial_id).failed
    monkeypatch.setattr(
        media_upload, "_utcnow", lambda: deadline + timedelta(seconds=1)
    )
    media_upload._expire_recordings()
    assert db.session.get(Recording, camera_id).upload_failed_reason == reason
    assert db.session.get(Trial, trial_id)._recording_failed
    assert not db.session.get(Participant, participant_id).failed


@pytest.mark.parametrize(
    "unavailable", [{"other": "queue_full"}, {"camera": {}}, {"camera": "unknown"}]
)
def test_invalid_unavailability_manifest_cannot_reserve_recordings(
    submission, unavailable
):
    _, _, _, submit = submission
    with pytest.raises(ValueError, match="unavailability manifest"):
        submit(unavailable=unavailable)
    assert Recording.query.count() == 0
