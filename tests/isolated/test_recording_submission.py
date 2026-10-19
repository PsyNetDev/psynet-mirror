"""Accepted video answers reserve uploads before the next page is consumed."""

import uuid

import pytest
from dallinger import db

from psynet.asset import LocalStorage
from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage, VideoRecordControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Response, Timeline
from psynet.trial.main import GenericTrialNode, Trial
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
        ).payload

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
    participant.answer = {}
    participant.answer_accumulation_depth = 1
    db.session.commit()
    assert submit()["submission"] == "approved"
    db.session.commit()
    db.session.expire_all()
    response = Response.query.filter_by(participant_id=participant.id).one()
    assert participant.answer == {"video": response.answer}
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


@pytest.fixture
def recording_trial(submission):
    """Attach a trial to the participant submitting a recording."""
    exp, participant, _, _ = submission
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
    return trial


def test_recordings_keep_the_original_trial_when_completion_moves_the_cursor(
    submission, recording_trial, monkeypatch
):
    _, participant, page, submit = submission
    trial = recording_trial
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
def test_unavailable_recording_fails_only_its_trial_immediately(
    submission, recording_trial, monkeypatch, size, unavailable, reason
):
    """A source the browser reports unavailable fails its trial without waiting."""
    exp, participant, _, submit = submission
    monkeypatch.delenv("PASSTHROUGH_ERRORS")
    monkeypatch.setattr(type(exp), "report_error", lambda *args, **kwargs: None)
    participant_id, trial_id = participant.id, recording_trial.id
    result = submit({"camera": size, "screen": 10}, unavailable)
    assert result["submission"] == "approved"
    assert {slot["source"] for slot in result["recording_uploads"]} == {"screen"}
    camera = Recording.query.filter_by(local_key="video_camera").one()
    assert camera.upload_token_hash is None
    assert (camera.upload_status, camera.upload_failed_reason) == ("failed", reason)
    assert camera.upload_context["captured_size_bytes"] == size
    db.session.commit()
    assert db.session.get(Trial, trial_id)._recording_failed
    assert not db.session.get(Participant, participant_id).failed


def test_legacy_video_answer_rejects_an_empty_recording(submission, tmp_path):
    """A failed capture must not be stored as if it were a valid recording."""
    from psynet.modular_page import Blob

    exp, participant, page, _ = submission
    page.control._async_upload = False
    empty = tmp_path / "empty.webm"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="recording is empty"):
        exp.process_response(
            participant_id=participant.id,
            raw_answer=None,
            blobs={"cameraRecording": Blob(empty), "screenRecording": Blob(empty)},
            metadata={"time_taken": 5},
            page_uuid=participant.page_uuid,
            client_ip_address="127.0.0.1",
        )
    assert Recording.query.count() == 0


def test_bots_declare_recordings_for_upload_after_acceptance(submission):
    """Bots use the same answer and upload routes as browsers."""
    from pathlib import Path

    exp, _, page, _ = submission
    video = (
        Path(__file__).resolve().parents[2]
        / "demos/features/video/example_video_recording.webm"
    )
    page.control.bot_response_media = {"camera": str(video), "screen": str(video)}
    response = page.control.get_bot_response(exp, bot=None, page=page, prompt=None)
    size = video.stat().st_size
    assert response.metadata["recording_uploads"] == {"camera": size, "screen": size}
    assert set(response.blobs) == {"cameraRecording", "screenRecording"}


def test_custom_record_controls_keep_uploading_with_the_answer(submission):
    """A subclass that does not opt in renders and submits as before."""
    from psynet.modular_page import RecordControl

    class CustomRecordControl(RecordControl):
        macro = "audio_record"

    exp, _, _, _ = submission
    control = CustomRecordControl(duration=1)
    assert not control._uses_async_upload(exp)
    assert control.get_js_vars()["asynchronousUploadSources"] is None


@pytest.mark.parametrize("size, uploads", [(1000, 1), (8 * 1024**2, 0)])
def test_audio_answers_upload_after_acceptance(submission, monkeypatch, size, uploads):
    """Audio answers use the same deferred path as video, as WAV files."""
    from pathlib import Path

    from psynet.modular_page import AudioRecordControl

    exp, participant, _, _ = submission
    control = AudioRecordControl(duration=3)
    page = ModularPage("audio", "Record", control, time_estimate=3)
    timeline = Timeline(page, InfoPage("Continue", time_estimate=1))
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    db.session.commit()
    # 4.5 s of headroom over 3 s at up to 192 kHz, 16-bit mono, plus the header.
    assert control._recording_max_bytes() == 44 + 9.5 * 192_000 * 2
    result = exp.process_response(
        participant_id=participant.id,
        raw_answer=None,
        blobs={},
        metadata={
            "time_taken": 3,
            "recording_uploads": {"audio": size},
            "recording_upload_unavailable": {},
        },
        page_uuid=participant.page_uuid,
        client_ip_address="127.0.0.1",
    ).payload
    assert result["submission"] == "approved"
    assert len(result["recording_uploads"]) == uploads
    recording = Recording.query.filter_by(local_key="audio").one()
    assert (recording.extension, recording.upload_context["format"]) == (".wav", "wav")
    assert participant.answer["asset_id"] == recording.id
    assert participant.answer["url"] == recording.url
    if not uploads:
        assert recording.upload_failed_reason == "size_limit"

    bot_file = (
        Path(__file__).resolve().parents[2]
        / "demos/features/video/example_audio_recording.wav"
    )
    control.bot_response_media = str(bot_file)
    bot = control.get_bot_response(exp, bot=None, page=page, prompt=None)
    assert bot.metadata["recording_uploads"] == {"audio": bot_file.stat().st_size}


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


def test_lost_acceptance_replays_original_slots_without_advancing(
    submission, monkeypatch
):
    import json
    from datetime import timedelta

    from psynet import media_upload

    exp, participant, page, _ = submission
    page_uuid = participant.page_uuid
    secret = "ab" * 32
    metadata = {
        "time_taken": 5,
        "recording_uploads": {"camera": 100, "screen": 100},
        "recording_recovery_secret": secret,
    }
    completions = []
    monkeypatch.setattr(page, "on_complete", lambda **kwargs: completions.append(True))

    def submit(key=secret, original_page=page_uuid):
        return exp.process_response(
            participant.id,
            None,
            {},
            {**metadata, "recording_recovery_secret": key},
            original_page,
            "127.0.0.1",
        ).payload

    accepted = submit()
    db.session.commit()
    successor = participant.page_uuid
    deadline = Recording.query.first().upload_deadline
    response = Response.query.one()
    assert secret not in json.dumps(response.metadata)
    assert secret not in json.dumps(response.recording_receipt)
    for receipt in accepted["recording_uploads"]:
        assert receipt["token"] not in json.dumps(response.recording_receipt)
        media_upload._authorize(
            db.session.get(Recording, int(receipt["id"])), receipt["token"]
        )
    replay_time = deadline + timedelta(seconds=1)
    monkeypatch.setattr(media_upload, "_utcnow", lambda: replay_time)
    replayed = submit()
    # Deadlines stay as issued; the replay's server time lets the browser
    # compute how much of them remains.
    assert replayed.pop("recording_upload_server_time") == replay_time.isoformat() + "Z"
    accepted.pop("recording_upload_server_time")
    assert replayed == accepted
    assert participant.page_uuid == successor
    assert completions == [True]
    assert Response.query.count() == 1
    assert Recording.query.count() == 2
    assert Recording.query.first().upload_deadline == deadline
    assert submit("cd" * 32)["submission"] == "rejected"
    assert submit(original_page=successor)["submission"] == "rejected"
    assert participant.page_uuid == successor
    from types import SimpleNamespace

    from werkzeug.exceptions import Gone

    assert (
        media_upload._recover_recording_receipt(
            SimpleNamespace(id=participant.id + 1), page_uuid, secret
        )
        is None
    )
    with pytest.raises(Gone):
        media_upload._check_receivable(Recording.query.first())
    participant.page_uuid = "later-page"
    db.session.commit()
    assert submit()["submission"] == "rejected"


@pytest.mark.parametrize(
    "inplace, local_storage, asynchronous",
    [(True, True, True), (False, True, False), (True, False, False)],
)
def test_default_video_transport_preserves_legacy_and_other_storage(
    submission, monkeypatch, inplace, local_storage, asynchronous
):
    from psynet.asset import NoStorage
    from psynet.utils import get_config

    exp, _, _, _ = submission
    control = VideoRecordControl(duration=1)
    config = get_config()
    original_get = config.get
    monkeypatch.setattr(
        config,
        "get",
        lambda key, *args: (
            inplace
            if key == "inplace_timeline_transitions"
            else original_get(key, *args)
        ),
    )
    if not local_storage:
        monkeypatch.setattr(exp, "asset_storage", NoStorage())
    assert control._uses_async_upload(exp) is asynchronous


def test_recording_recovery_uses_prepared_successor(submission, monkeypatch):
    """HTTP retries retain upload slots while rendering the prepared next page."""
    import json

    from flask import Flask

    exp, participant, _, _ = submission
    original_uuid = participant.page_uuid
    successor = next(
        elt for elt in exp.timeline.elts["main"] if isinstance(elt, InfoPage)
    )
    monkeypatch.setattr(
        successor,
        "pre_render",
        lambda: setattr(successor, "contents", {"prepared": True}),
    )
    monkeypatch.setattr(
        Experiment, "_render_page_read_only", lambda **kwargs: "<div>Next page</div>"
    )
    payload = {
        "participant_id": participant.id,
        "page_uuid": original_uuid,
        "raw_answer": None,
        "metadata": {
            "time_taken": 5,
            "recording_uploads": {"camera": 100, "screen": 100},
            "recording_recovery_secret": "ab" * 32,
        },
        "include_timeline_fragment": True,
    }

    def submit():
        with Flask(__name__).test_request_context(
            "/response",
            method="POST",
            data={"json": json.dumps(payload)},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            return exp.route_response().get_json()

    accepted = submit()
    replay = submit()
    assert accepted["submission"] == replay["submission"] == "approved"
    assert (
        accepted["page"]["contents"] == replay["page"]["contents"] == {"prepared": True}
    )
    assert accepted["recording_uploads"] == replay["recording_uploads"]
    assert "timeline_fragment" in replay
    assert Response.query.count() == 1
    assert Recording.query.count() == 2
    stored = json.dumps(Response.query.one().recording_receipt)
    assert all(upload["token"] not in stored for upload in replay["recording_uploads"])
