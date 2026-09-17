"""Exercise reservation and receipt against real PostgreSQL and streamed bodies."""

import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from dallinger import db
from flask import Flask
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden, Gone, RequestEntityTooLarge

from psynet.asset import LocalStorage
from psynet.experiment import Experiment, get_experiment
from psynet.media_upload import _receive_recording, _reserve_recording
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Response
from psynet.trial.record import Recording

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


@pytest.fixture
def reservation(db_session, tmp_path):
    """Reserve a recording as part of a committed, accepted page response."""
    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    db.session.flush()
    response = Response(participant=participant, label="video", page_type="ModularPage")
    response.successful_validation = True
    db.session.add(response)
    asset, receipt = _reserve_recording(
        response=response,
        parent=participant,
        page_uuid="original-page",
        source="camera",
        local_key="video",
        storage=LocalStorage(str(tmp_path / "assets")),
        max_bytes=100,
    )
    db.session.commit()
    return asset, receipt


def test_reservation_retains_original_identity_without_deposit(reservation):
    asset, receipt = reservation
    assert asset.upload_status == "pending"
    assert asset.upload_context["page_uuid"] == "original-page"
    assert asset.upload_context["source"] == "camera"
    assert asset.parent.assets["video"] is asset
    assert asset.input_path is None
    assert not asset.deposited
    assert receipt["token"] != asset.access_token
    assert receipt["token"] != asset.upload_token_hash


def test_complete_receipt_is_unavailable_until_deposit(reservation, tmp_path):
    asset, receipt = reservation
    _receive_recording(
        asset.id, receipt["token"], io.BytesIO(b"recording"), directory=tmp_path
    )
    db.session.refresh(asset)
    assert asset.upload_status == "received"
    assert Path(asset.input_path).read_bytes() == b"recording"
    assert asset.upload_processing_deadline > asset.upload_received_at
    assert not asset.deposited
    with Flask(__name__).test_request_context():
        from werkzeug.exceptions import NotFound

        with pytest.raises(NotFound):
            asset.serve()


def test_bad_capability_does_not_read_the_body(reservation, tmp_path):
    asset, receipt = reservation
    body = io.BytesIO(b"private bytes")
    for token in ["wrong", "", asset.access_token]:
        with pytest.raises(Forbidden):
            _receive_recording(asset.id, token, body, directory=tmp_path)
    assert body.tell() == 0
    assert not list(tmp_path.glob("psynet-upload-*"))


def test_oversized_stream_is_discarded(reservation, tmp_path):
    asset, receipt = reservation
    with pytest.raises(RequestEntityTooLarge):
        _receive_recording(
            asset.id, receipt["token"], io.BytesIO(b"x" * 101), directory=tmp_path
        )
    db.session.refresh(asset)
    assert asset.upload_status == "pending"
    assert asset.input_path is None
    assert not list(tmp_path.glob("psynet-upload-*"))


def test_late_receipt_cannot_publish_bytes(reservation, tmp_path):
    asset, receipt = reservation
    asset.upload_deadline = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=1
    )
    db.session.commit()
    with pytest.raises(Gone):
        _receive_recording(
            asset.id, receipt["token"], io.BytesIO(b"late"), directory=tmp_path
        )
    assert not list(tmp_path.glob("psynet-upload-*"))


def test_retry_after_lost_receipt_cannot_overwrite(reservation, tmp_path):
    asset, receipt = reservation
    _receive_recording(
        asset.id, receipt["token"], io.BytesIO(b"original"), directory=tmp_path
    )
    _receive_recording(
        asset.id, receipt["token"], io.BytesIO(b"replacement"), directory=tmp_path
    )
    db.session.refresh(asset)
    assert Path(asset.input_path).read_bytes() == b"original"
    assert len(list(tmp_path.glob("psynet-upload-*"))) == 1


def test_simultaneous_receipts_publish_only_one_file(reservation, tmp_path):
    asset, receipt = reservation
    recording_id = asset.id
    barrier = Barrier(2)

    class Body(io.BytesIO):
        def read(self, size=-1):
            chunk = super().read(size)
            if not chunk:
                barrier.wait(timeout=5)
            return chunk

    def receive(payload):
        _receive_recording(
            recording_id, receipt["token"], Body(payload), directory=tmp_path
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(receive, [b"first", b"second"]))
    db.session.refresh(asset)
    assert Path(asset.input_path).read_bytes() in [b"first", b"second"]
    assert len(list(tmp_path.glob("psynet-upload-*"))) == 1


def test_rolled_back_response_leaves_no_recording_slot(reservation):
    asset, receipt = reservation
    response = db.session.get(Response, asset.upload_context["response_id"])
    pending, _ = _reserve_recording(
        response=response,
        parent=asset.parent,
        page_uuid="rollback",
        source="camera",
        local_key="rollback",
        storage=asset.storage,
    )
    recording_id = pending.id
    db.session.rollback()
    with Session(db.engine) as session:
        assert session.get(Recording, recording_id) is None


def test_streaming_holds_no_participant_or_asset_lock(reservation, tmp_path):
    asset, receipt = reservation

    class Body(io.BytesIO):
        def read(self, size=-1):
            with Session(db.engine) as session, session.begin():
                session.query(Participant).filter_by(
                    id=asset.participant_id
                ).with_for_update(of=Participant, nowait=True).one()
                session.query(Recording).filter_by(id=asset.id).with_for_update(
                    nowait=True
                ).one()
            return super().read(size)

    _receive_recording(
        asset.id, receipt["token"], Body(b"recording"), directory=tmp_path
    )


def test_expiry_during_stream_cannot_be_undone_by_receipt(reservation, tmp_path):
    asset, receipt = reservation

    class Body(io.BytesIO):
        def read(self, size=-1):
            with Session(db.engine) as session, session.begin():
                recording = session.get(Recording, asset.id)
                recording.upload_status = "expired"
            return super().read(size)

    with pytest.raises(Gone):
        _receive_recording(
            asset.id, receipt["token"], Body(b"recording"), directory=tmp_path
        )
    db.session.refresh(asset)
    assert asset.upload_status == "expired"
    assert asset.input_path is None
    assert not list(tmp_path.glob("psynet-upload-*"))


def test_rejected_answer_cannot_reserve_a_recording(reservation):
    asset, receipt = reservation
    response = db.session.get(Response, asset.upload_context["response_id"])
    response.successful_validation = False
    with pytest.raises(ValueError, match="accepted"):
        _reserve_recording(
            response=response,
            parent=asset.parent,
            page_uuid="rejected",
            source="camera",
            local_key="rejected",
            storage=asset.storage,
        )
    assert "rejected" not in asset.parent.assets


def test_route_accepts_raw_body_with_bearer_capability(reservation):
    asset, receipt = reservation
    app = Flask(__name__)
    app.add_url_rule(
        "/media-upload/<int:recording_id>",
        view_func=Experiment.receive_media_upload,
        methods=["POST"],
    )
    with app.test_client() as client:
        response = client.post(
            f"/media-upload/{asset.id}",
            data=b"recording",
            headers={"Authorization": f"Bearer {receipt['token']}"},
        )
    assert response.status_code == 204
    db.session.refresh(asset)
    Path(asset.input_path).unlink()
