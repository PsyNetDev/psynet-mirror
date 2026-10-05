"""Exercise reservation and receipt against real PostgreSQL and streamed bodies."""

import io
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread

import pytest
from dallinger import db
from flask import Flask
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest, Forbidden, Gone, RequestEntityTooLarge
from werkzeug.serving import make_server

from psynet.asset import LocalStorage
from psynet.experiment import Experiment, get_experiment
from psynet.media_upload import (
    _expire_recordings,
    _process_recording,
    _receive_recording,
    _reserve_recording,
    _upload_directory,
    _upload_timeout,
)
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


@pytest.mark.parametrize("size", [0, -1, True, 1.5, None])
def test_upload_allowance_rejects_invalid_size(size):
    with pytest.raises(ValueError):
        _upload_timeout(size)


@pytest.mark.parametrize("ssh", [False, True])
def test_upload_spool_uses_private_shared_deployment_directory(monkeypatch, ssh):
    from psynet import deployment_info

    monkeypatch.setattr(deployment_info, "read", lambda key: ssh)
    expected = Path("/var/lib/dallinger") if ssh else Path.cwd() / ".deploy"
    assert _upload_directory() == expected / "media-uploads"


@pytest.fixture
def reservation(db_session, tmp_path, monkeypatch):
    """Reserve a recording as part of a committed, accepted page response."""
    monkeypatch.setattr(
        "psynet.deployment_info.read_all",
        lambda: {
            "deployment_id": "test-deployment",
            "is_local_deployment": True,
            "is_ssh_deployment": False,
        },
    )
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


@pytest.mark.parametrize(
    "size, override, seconds",
    [
        (1, None, 60),
        (1024**2, None, 60),
        (10 * 1024**2, None, 198),
        (128 * 1024**2, None, 600),
        (None, None, 600),
        (10 * 1024**2, 75, 75),
    ],
)
def test_reservation_fixes_size_based_or_explicit_deadline(
    reservation, monkeypatch, size, override, seconds
):
    asset, _ = reservation
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr("psynet.media_upload._utcnow", lambda: now)
    response = db.session.get(Response, asset.upload_context["response_id"])
    pending, _ = _reserve_recording(
        response=response,
        parent=asset.parent,
        page_uuid="sized",
        source="camera",
        local_key="sized",
        storage=asset.storage,
        upload_size_bytes=size,
        upload_timeout=override,
    )
    assert pending.upload_deadline == now + timedelta(seconds=seconds)
    assert pending.upload_context["upload_size_bytes"] == size


def test_complete_receipt_is_unavailable_until_deposit(reservation, tmp_path):
    asset, receipt = reservation
    _receive_recording(
        asset.id,
        receipt["token"],
        io.BytesIO(b"\x1aE\xdf\xa3recording"),
        directory=tmp_path,
    )
    db.session.refresh(asset)
    assert asset.upload_status == "received"
    assert Path(asset.input_path).read_bytes() == b"\x1aE\xdf\xa3recording"
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
        asset.id,
        receipt["token"],
        io.BytesIO(b"\x1aE\xdf\xa3original"),
        directory=tmp_path,
    )
    _receive_recording(
        asset.id, receipt["token"], io.BytesIO(b"replacement"), directory=tmp_path
    )
    db.session.refresh(asset)
    assert Path(asset.input_path).read_bytes() == b"\x1aE\xdf\xa3original"
    assert len(list(tmp_path.glob("psynet-upload-*"))) == 1


def test_simultaneous_receipt_is_rejected_without_reading(reservation, tmp_path):
    from threading import Event

    from werkzeug.exceptions import TooManyRequests

    asset, receipt = reservation
    recording_id = asset.id
    started, release = Event(), Event()

    class Body(io.BytesIO):
        def read(self, size=-1):
            started.set()
            assert release.wait(timeout=5)
            return super().read(size)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            _receive_recording,
            recording_id,
            receipt["token"],
            Body(b"\x1aE\xdf\xa3first"),
            directory=tmp_path,
        )
        try:
            assert started.wait(timeout=5)
            second = io.BytesIO(b"second")
            with pytest.raises(TooManyRequests):
                _receive_recording(
                    recording_id, receipt["token"], second, directory=tmp_path
                )
            assert second.tell() == 0
        finally:
            release.set()
        first.result(timeout=5)
    db.session.refresh(asset)
    assert Path(asset.input_path).read_bytes() == b"\x1aE\xdf\xa3first"


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
        asset.id, receipt["token"], Body(b"\x1aE\xdf\xa3recording"), directory=tmp_path
    )


def test_expiry_during_stream_cannot_be_undone_by_receipt(
    reservation, tmp_path, monkeypatch
):
    from psynet import media_upload

    monkeypatch.setattr(media_upload, "_upload_directory", lambda: tmp_path)
    asset, receipt = reservation

    class Body(io.BytesIO):
        def read(self, size=-1):
            with Session(db.engine) as session, session.begin():
                recording = session.get(Recording, asset.id)
                recording.upload_status = "expired"
            media_upload._clean_abandoned_receipts()
            assert len(list(tmp_path.glob("psynet-upload-*"))) == 1
            return super().read(size)

    with pytest.raises(Gone):
        _receive_recording(
            asset.id,
            receipt["token"],
            Body(b"\x1aE\xdf\xa3recording"),
            directory=tmp_path,
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


@pytest.mark.parametrize("supports_deadline", [True, False])
def test_route_accepts_raw_body_only_with_a_bounded_connection(
    reservation, supports_deadline
):
    asset, receipt = reservation
    app = Flask(__name__)
    app.add_url_rule(
        "/media-upload/<int:recording_id>",
        view_func=Experiment.receive_media_upload,
        methods=["POST"],
    )
    with socket.socket() as connection, app.test_client() as client:
        response = client.post(
            f"/media-upload/{asset.id}",
            data=b"\x1aE\xdf\xa3recording",
            headers={"Authorization": f"Bearer {receipt['token']}"},
            environ_overrides={"werkzeug.socket": connection}
            if supports_deadline
            else {},
        )
    assert response.status_code == (204 if supports_deadline else 503)
    db.session.refresh(asset)
    if supports_deadline:
        Path(asset.input_path).unlink()
    else:
        assert asset.input_path is None


def test_stalled_http_upload_is_interrupted_at_deadline(reservation):
    """A real partial HTTP body must release the request worker by its deadline."""
    asset, receipt = reservation
    app = Flask(__name__)
    app.add_url_rule(
        "/media-upload/<int:recording_id>",
        view_func=Experiment.receive_media_upload,
        methods=["POST"],
    )
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    asset.upload_deadline = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        seconds=2
    )
    db.session.commit()
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=5) as client:
            client.sendall(
                (
                    f"POST /media-upload/{asset.id} HTTP/1.1\r\nHost: localhost\r\n"
                    f"Authorization: Bearer {receipt['token']}\r\nContent-Length: 9\r\n\r\nx"
                ).encode()
            )
            response = client.recv(4096)
            assert b"410 GONE" in response
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    db.session.refresh(asset)
    assert asset.input_path is None
    assert not asset.deposited


@pytest.fixture
def received_video(reservation, tmp_path, monkeypatch, request):
    """Receive test bytes through the same pipeline used by the HTTP route."""
    path = (
        Path(__file__).resolve().parents[2]
        / "demos/experiments/imitation_chain_video/assets/example_recording.webm"
    )
    payload = (
        b"\x1aE\xdf\xa3header only"
        if getattr(request, "param", "webm") == "header_only"
        else path.read_bytes()
    )
    asset, receipt = reservation
    asset.upload_max_bytes = len(payload)
    recording_id = asset.id
    db.session.commit()
    _receive_recording(
        recording_id, receipt["token"], io.BytesIO(payload), directory=tmp_path
    )
    monkeypatch.setattr(LocalStorage, "on_deployed_server", lambda self: True)
    return recording_id, payload


@pytest.mark.parametrize(
    "received_video",
    ["webm", "header_only"],
    indirect=["received_video"],
)
def test_received_bytes_are_deposited_unchanged(received_video):
    import hashlib

    recording_id, payload = received_video
    _process_recording(recording_id)
    asset = db.session.get(Recording, recording_id)
    assert asset.upload_status == "deposited"
    assert asset.deposited
    assert asset.sha256_contents == hashlib.sha256(payload).hexdigest()
    assert (
        Path(asset.storage.get_file_system_path(asset.host_path)).read_bytes()
        == payload
    )
    assert asset.input_path is None
    assert asset.upload_failed_reason is None
    assert not asset.participant.failed


@pytest.mark.parametrize("payload", [b"not media", b"\x1aE", b"\x1aE\xdf\xa3payload"])
def test_receiver_checks_header_across_short_reads(reservation, tmp_path, payload):
    class ShortReads(io.BytesIO):
        def read(self, size):
            return super().read(min(size, 1))

    asset, receipt = reservation
    if payload.startswith(b"\x1aE\xdf\xa3"):
        _receive_recording(
            asset.id, receipt["token"], ShortReads(payload), directory=tmp_path
        )
        db.session.refresh(asset)
        assert asset.upload_status == "received"
        assert Path(asset.input_path).read_bytes() == payload
    else:
        with pytest.raises(BadRequest, match="WebM/EBML"):
            _receive_recording(
                asset.id, receipt["token"], ShortReads(payload), directory=tmp_path
            )
        db.session.refresh(asset)
        assert asset.upload_status == "pending"
        assert asset.input_path is None
        assert not list(tmp_path.glob("psynet-upload-*"))
    assert not asset.deposited


def test_missing_upload_expires_without_a_browser_request(reservation):
    asset, _ = reservation
    recording_id = asset.id
    asset.upload_deadline = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=1
    )
    db.session.commit()
    _expire_recordings()
    asset = db.session.get(Recording, recording_id)
    assert asset.upload_status == "expired"
    assert asset.upload_failed_reason == "upload_timeout"


def test_late_deposit_cannot_revive_an_expired_recording(received_video, monkeypatch):
    import psynet.media_upload as uploads

    recording_id, _ = received_video
    store = uploads._store_recording_bytes

    def expire_before_publication(*args):
        output = store(*args)
        asset = db.session.get(Recording, recording_id)
        asset.upload_processing_deadline = uploads._utcnow() - timedelta(seconds=1)
        db.session.commit()
        uploads._expire_recordings()
        return output

    monkeypatch.setattr(uploads, "_store_recording_bytes", expire_before_publication)
    _process_recording(recording_id)
    asset = db.session.get(Recording, recording_id)
    assert asset.upload_status == "expired"
    assert asset.upload_failed_reason == "processing_timeout"
    assert not asset.deposited


def test_storage_failure_leaves_recording_unavailable(received_video, monkeypatch):
    recording_id, _ = received_video

    def fail_copy(*args):
        raise OSError("Disk full")

    monkeypatch.setattr(LocalStorage, "_receive_deposit", fail_copy)
    _process_recording(recording_id)
    asset = db.session.get(Recording, recording_id)
    assert asset.upload_status == "failed"
    assert asset.upload_failed_reason == "processing_error"
    assert not asset.deposited


def test_received_recording_is_queued_only_once(received_video, monkeypatch):
    from psynet.media_upload import _queue_received_recordings
    from psynet.process import WorkerAsyncProcess

    recording_id, _ = received_video
    launched = []
    monkeypatch.setattr(
        WorkerAsyncProcess, "launch", lambda spec: launched.append(spec["id"])
    )
    _queue_received_recordings()
    _queue_received_recordings()
    assert len(launched) == 1
    assert db.session.get(Recording, recording_id).upload_status == "queued"
    WorkerAsyncProcess.call_function(launched[0])
    assert db.session.get(Recording, recording_id).deposited
    process = db.session.get(WorkerAsyncProcess, launched[0])
    assert process.finished and not process.pending and not process.failed


@pytest.mark.parametrize("retry", [False, True])
def test_receiver_crash_releases_ownership_and_cleans_partials(
    reservation, tmp_path, monkeypatch, retry
):
    import multiprocessing
    import os
    from datetime import timedelta

    from psynet import media_upload

    asset, receipt = reservation
    asset.upload_max_bytes = 65536
    asset_id, deadline = asset.id, asset.upload_deadline
    db.session.commit()

    def crash_receiver():
        db.engine.dispose(close=False)

        class Body:
            first = True

            def read(self, size):
                if self.first:
                    self.first = False
                    return b"x" * 65536
                os._exit(23)

        _receive_recording(asset_id, receipt["token"], Body(), directory=tmp_path)

    process = multiprocessing.get_context("fork").Process(target=crash_receiver)
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail("Receiver did not exit in time")
    assert process.exitcode == 23
    files = list(tmp_path.glob("psynet-upload-*"))
    assert len(files) == 1 and files[0].stat().st_size == 65536
    if retry:
        _receive_recording(
            asset_id,
            receipt["token"],
            io.BytesIO(b"\x1aE\xdf\xa3retry"),
            directory=tmp_path,
        )
        assert not files[0].exists()
        assert len(list(tmp_path.glob("psynet-upload-*"))) == 1
        db.session.refresh(asset)
        assert Path(asset.input_path).read_bytes() == b"\x1aE\xdf\xa3retry"
        return
    monkeypatch.setattr(
        media_upload, "_utcnow", lambda: deadline + timedelta(seconds=1)
    )
    monkeypatch.setattr(media_upload, "_upload_directory", lambda: tmp_path)
    media_upload._expire_recordings()
    assert db.session.get(Recording, asset_id).upload_status == "expired"
    assert db.session.get(Recording, asset_id).input_path is None
    assert not files[0].exists()


def test_request_expiry_does_not_commit_navigation(reservation, monkeypatch):
    """Expiry performed by a participant request rolls back with that request."""
    from psynet import media_upload

    asset, _ = reservation
    recording_id, participant_id = asset.id, asset.participant_id
    deadline = asset.upload_deadline
    db.session.commit()
    monkeypatch.setattr(
        media_upload, "_utcnow", lambda: deadline + timedelta(seconds=1)
    )
    media_upload._expire_participant_recordings(participant_id)
    assert db.session.get(Recording, recording_id).upload_status == "expired"
    db.session.rollback()
    assert db.session.get(Recording, recording_id).upload_status == "pending"
