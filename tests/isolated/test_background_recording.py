"""Background media must not change ordinary answers or required dependencies."""

import pytest
from dallinger import db
from test_recording_submission import pytestmark as pytestmark
from test_recording_submission import recording_trial as recording_trial
from test_recording_submission import submission as submission

from psynet.background_recording import VideoRecordConfig
from psynet.modular_page import ModularPage, PushButtonControl, VideoRecordControl
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.trial.main import Trial
from psynet.trial.record import Recording, RecordTrial


def test_configuration_rejects_conflicts():
    with pytest.raises(ValueError, match="answer recorder"):
        ModularPage(
            "bad",
            "Record",
            VideoRecordControl(duration=1),
            background_recording="camera",
        )
    with pytest.raises(ValueError, match="source"):
        VideoRecordConfig(source="video")


@pytest.mark.parametrize(
    "inplace,local,error", [(False, True, "in-place"), (True, False, "LocalStorage")]
)
def test_background_environment_is_checked_at_startup(
    submission, monkeypatch, inplace, local, error
):
    from psynet.asset import LocalStorage, NoStorage

    exp, _, _, _ = submission
    monkeypatch.setattr(
        exp,
        "timeline",
        Timeline(InfoPage("Capture", time_estimate=1, background_recording="camera")),
    )
    monkeypatch.setattr(exp, "asset_storage", LocalStorage() if local else NoStorage())
    monkeypatch.setattr(
        "psynet.utils.get_config", lambda: {"inplace_timeline_transitions": inplace}
    )
    with pytest.raises(ValueError, match=error):
        exp._check_static_spa_contracts()


def test_recording_labels_use_participant_translation(monkeypatch):
    from psynet.background_recording import _recording_labels

    monkeypatch.setattr(
        "psynet.utils.get_translator", lambda: lambda text: "translated: " + text
    )
    monkeypatch.setattr(
        "psynet.modular_page.get_translator", lambda: lambda text: "translated: " + text
    )
    assert all(
        label.startswith("translated: ") for label in _recording_labels().values()
    )


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("unavailable", [{}, {"camera": "permission_denied"}])
def test_background_answer_and_expiry(
    submission, recording_trial, monkeypatch, required, unavailable
):
    from datetime import timedelta

    from psynet import media_upload

    exp, participant, _, _ = submission
    timeline = Timeline(
        ModularPage(
            "choice",
            "Choose",
            PushButtonControl(["Yes", "No"]),
            background_recording=VideoRecordConfig(required=required),
            time_estimate=1,
        ),
        InfoPage("Continue", time_estimate=1),
    )
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    trial = recording_trial
    db.session.commit()
    if required:

        def on_complete(experiment, participant):
            assert participant.current_trial.asset_deposit_pending
            assert participant.answer == "Yes"

        monkeypatch.setattr(
            timeline.get_current_elt(exp, participant), "on_complete", on_complete
        )
    trial_id, participant_id, page_uuid = (
        trial.id,
        participant.id,
        participant.page_uuid,
    )

    def submit():
        return exp.process_response(
            participant.id,
            "Yes",
            {},
            {
                "time_taken": 1,
                "background_recording": {
                    "sizes": {"camera": 100},
                    "unavailable": unavailable,
                },
            },
            page_uuid,
            "127.0.0.1",
        ).payload

    result = submit()
    assert result["submission"] == "approved"
    assert participant.answer == "Yes"
    asset = Recording.query.one()
    assert asset.recording_role == "background"
    assert asset.upload_context["page_uuid"] == page_uuid
    assert trial.asset_deposit_pending is required
    assert (
        db.session.query(Trial.asset_deposit_pending)
        .filter(Trial.id == trial_id)
        .scalar()
    ) is required
    assert RecordTrial.recording.fget(trial) is None
    deadline = asset.upload_deadline
    db.session.commit()
    media_upload._expire_recordings()
    assert not db.session.get(Trial, trial_id).failed
    monkeypatch.setattr(
        media_upload, "_utcnow", lambda: deadline + timedelta(seconds=1)
    )
    media_upload._expire_recordings()
    assert db.session.get(Trial, trial_id).failed is required
    assert not db.session.get(type(participant), participant_id).failed
    media_upload._expire_recordings()
    assert db.session.get(Trial, trial_id).failed is required


@pytest.mark.parametrize(
    "consent_class,key",
    [
        ("AudiovisualConsent", "audiovisual_consent"),
        ("LabRecruiterAudiovisualConsent", "lab-recruiter_audiovisual_consent"),
    ],
)
def test_stock_consent_requires_stored_acceptance(
    submission, monkeypatch, consent_class, key
):
    from psynet import consent
    from psynet.background_recording import _browser_config

    exp, participant, _, _ = submission
    page = InfoPage("Observe", background_recording="camera", time_estimate=1)
    monkeypatch.setattr(
        exp,
        "timeline",
        Timeline(getattr(consent, consent_class)(time_estimate=1), page),
    )
    with pytest.raises(ValueError, match="stored audiovisual consent"):
        _browser_config(page, exp, participant)
    participant.var.set(key, True)
    assert _browser_config(page, exp, participant)["sources"] == ["camera"]


def test_consent_pages_cannot_record():
    from psynet.consent import Consent
    from psynet.timeline import Page

    class ConsentPage(Page, Consent):
        pass

    with pytest.raises(ValueError, match="Consent pages"):
        ConsentPage(background_recording="camera")


@pytest.mark.parametrize("required", [False, True])
def test_rejected_background_answer_creates_no_assets(
    submission, monkeypatch, request, required
):
    if required:
        request.getfixturevalue("recording_trial")
    exp, participant, _, _ = submission
    completions = []
    page = ModularPage(
        "choice",
        "Choose",
        PushButtonControl(["Yes"]),
        time_estimate=1,
        background_recording=VideoRecordConfig(source="both", required=required),
    )
    monkeypatch.setattr(
        exp, "timeline", Timeline(page, InfoPage("Continue", time_estimate=1))
    )
    participant.elt_id = ["main", -1]
    exp.timeline.advance_page(exp, participant)
    db.session.commit()
    original_page = participant.page_uuid
    original_answer = participant.answer
    monkeypatch.setattr(page, "on_complete", lambda **kwargs: completions.append(True))
    validate = page.validate
    monkeypatch.setattr(page, "validate", lambda **kwargs: "Try again")

    def submit():
        return exp.process_response(
            participant.id,
            "Yes",
            {},
            {
                "time_taken": 1,
                "background_recording": {"sizes": {"camera": 100, "screen": 100}},
            },
            original_page,
            "127.0.0.1",
        ).payload

    assert submit()["submission"] == "rejected"
    assert completions == ([] if required else [True])
    assert participant.answer == (original_answer if required else "Yes")
    assert Recording.query.count() == 0
    assert participant.page_uuid == original_page
    monkeypatch.setattr(page, "validate", validate)
    assert len(submit()["recording_uploads"]) == 2
    assert completions == ([True] if required else [True, True])
    assert participant.answer == "Yes"


def test_required_assets_still_block_trial(recording_trial, tmp_path):
    from psynet.asset import FileAsset

    trial = recording_trial
    path = tmp_path / "pending.txt"
    path.write_text("pending")
    required = FileAsset(parent=trial, local_key="required", input_path=str(path))
    optional = FileAsset(parent=trial, local_key="optional", input_path=str(path))
    optional.required_for_trial = False
    trial.assets["required"] = required
    trial.assets["optional"] = optional
    db.session.add_all([required, optional])
    db.session.flush()
    assert trial.asset_deposit_pending
    assert (
        db.session.query(Trial.asset_deposit_pending)
        .filter(Trial.id == trial.id)
        .scalar()
    )
    required.deposited = True
    db.session.flush()
    assert not trial.asset_deposit_pending
    assert (
        not db.session.query(Trial.asset_deposit_pending)
        .filter(Trial.id == trial.id)
        .scalar()
    )


def test_required_background_needs_trial(submission):
    from psynet.background_recording import _browser_config

    exp, participant, _, _ = submission
    page = InfoPage(
        "Observe",
        time_estimate=1,
        background_recording=VideoRecordConfig(required=True),
    )
    with pytest.raises(ValueError, match="parent trial"):
        _browser_config(page, exp, participant)
    with pytest.raises(ValueError, match="boolean"):
        VideoRecordConfig(required="yes")


def test_framework_task_pages_accept_background_capture():
    from psynet.page import JsPsychPage, UnityPage

    unity = UnityPage(
        "Unity",
        "/static/unity",
        {},
        "shared",
        time_estimate=1,
        background_recording="camera",
    )
    jspsych = JsPsychPage(
        "task",
        "/static/task.js",
        1,
        [],
        [],
        background_recording="camera",
    )
    shared = InfoPage(
        "Shared",
        time_estimate=1,
        session_id="shared",
        background_recording="camera",
    )
    assert all(
        page.background_recording.source == "camera"
        for page in (unity, jspsych, shared)
    )
    with pytest.raises(ValueError, match="Unity IDE"):
        UnityPage(
            "Unity",
            "/static/unity",
            {},
            "shared",
            time_estimate=1,
            debug=True,
            background_recording="camera",
        )


def test_same_session_payload_carries_next_capture_policy(submission, monkeypatch):
    exp, participant, _, _ = submission
    timeline = Timeline(
        InfoPage("First", time_estimate=1, session_id="shared"),
        InfoPage(
            "Second",
            time_estimate=1,
            session_id="shared",
            background_recording=VideoRecordConfig(source="screen"),
        ),
    )
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    original_uuid = participant.page_uuid
    timeline.advance_page(exp, participant)
    payload = exp._approved_payload(
        participant, timeline.get_current_elt(exp, participant)
    )
    attributes = payload["page"]["attributes"]
    assert attributes["session_id"] == "shared"
    assert attributes["page_uuid"] != original_uuid
    assert attributes["background_recording"]["sources"] == ["screen"]
