"""Internal reservation and receipt of asynchronous recordings.

Reservations belong to existing Recording assets and must be created in the
accepted response transaction. Read links and upload capabilities are separate;
only a hash of the write capability is stored. The receiver authenticates before
reading bytes, streams to a private bounded file without holding database locks,
then locks only the recording row to publish complete receipt exactly once.

Receipt is not deposit: a worker validates and stores bytes before a short
transaction publishes success. A poller expires overdue recordings even when
the browser has closed. This infrastructure is not yet enabled in controls.
Do not wrap the streaming route in a participant transaction or expose received
files through the asset endpoint before successful deposit.
"""

import errno
import hashlib
import json
import math
import os
import secrets
import socket
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Timer
from types import SimpleNamespace

from dallinger import db
from sqlalchemy.orm import Session
from werkzeug.exceptions import (
    BadRequest,
    ClientDisconnected,
    Forbidden,
    Gone,
    RequestEntityTooLarge,
)

from . import deployment_info
from .asset import LocalStorage
from .db import with_transaction
from .trial.record import Recording
from .utils import (
    content_object_path,
    get_file_size_mb,
    get_logger,
    md5_file,
    sha256_file,
)

logger = get_logger()


def _upload_timeout(size_bytes):
    """Allow a conservative 1 Mbit/s transfer, retry headroom, and queue overhead.

    This is an engineering allowance, not a measured participant average:
    30 seconds + twice the transfer time, bounded to 60–600 seconds. Compute
    once on acceptance; neither queueing nor retransmission resets the clock.
    """
    if type(size_bytes) is not int or size_bytes <= 0:
        raise ValueError("Recording size must be a positive integer.")
    return min(600, max(60, 30 + math.ceil(2 * size_bytes * 8 / 1_000_000)))


def _utcnow():
    """Return UTC without timezone information, matching existing DB dates."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _upload_directory():
    """Use private storage shared by web, worker, and clock processes.

    SSH deployments mount Dallinger's experiment data directory in every
    container. Local Docker mounts the experiment directory in every container;
    local virtualenv deployments also share that directory. Neither location is
    under the publicly served static asset tree.
    """
    root = (
        Path("/var/lib/dallinger")
        if deployment_info.read("is_ssh_deployment")
        else Path.cwd() / ".deploy"
    )
    return root / "media-uploads"


def _reserve_recording(
    *,
    response,
    parent,
    page_uuid,
    source,
    local_key,
    storage,
    upload_timeout=None,
    upload_size_bytes=None,
    processing_timeout=20,
    max_bytes=128 * 1024 * 1024,
):
    """Reserve a server-selected recording in the accepted answer transaction."""
    if not response.successful_validation:
        raise ValueError("Only accepted responses can reserve recordings.")
    if not isinstance(storage, LocalStorage):
        raise ValueError("Asynchronous recordings currently require LocalStorage.")
    if source not in {"camera", "screen"}:
        raise ValueError("A recording reservation must identify one capture source.")
    if any(
        type(value) is not int or value <= 0
        for value in (processing_timeout, max_bytes)
    ):
        raise ValueError("Recording limits must be positive integers.")
    if upload_size_bytes is not None and (
        type(upload_size_bytes) is not int or not 0 < upload_size_bytes <= max_bytes
    ):
        raise ValueError("Recording size must be positive and within the upload limit.")
    if upload_timeout is None:
        upload_timeout = _upload_timeout(
            max_bytes if upload_size_bytes is None else upload_size_bytes
        )
    if type(upload_timeout) is not int or upload_timeout <= 0:
        raise ValueError("Recording limits must be positive integers.")
    if local_key in parent.assets:
        raise ValueError(f"This parent already has an asset named {local_key!r}.")
    asset = Recording(
        input_path=None,
        is_folder=False,
        extension=".webm",
        local_key=local_key,
        parent=parent,
    )
    asset.input_path = None
    ancestors = asset.get_ancestors()
    if ancestors["participant"] != response.participant_id:
        raise ValueError("Recording and response must belong to the same participant.")
    db.session.add(response)
    db.session.flush()
    asset.storage = storage
    asset.ensure_keys_and_paths()
    parent.assets[local_key] = asset
    for kind in ("network", "node", "trial", "participant"):
        setattr(asset, f"{kind}_id", ancestors[kind])
    token = secrets.token_urlsafe(32)
    asset.upload_token_hash = hashlib.sha256(token.encode()).hexdigest()
    asset.upload_status = "pending"
    asset.upload_deadline = _utcnow() + timedelta(seconds=upload_timeout)
    asset.upload_max_bytes = max_bytes
    asset.upload_context = {
        "response_id": response.id,
        "page_uuid": page_uuid,
        "source": source,
        "processing_timeout": processing_timeout,
        "upload_size_bytes": upload_size_bytes,
    }
    db.session.add(asset)
    db.session.flush()
    return asset, {
        "id": str(asset.id),
        "url": f"/media-upload/{asset.id}",
        "token": token,
        "expires_at": asset.upload_deadline.replace(tzinfo=timezone.utc).isoformat(),
    }


def _authorize(recording, token):
    """Require the write capability, including for an idempotent retry."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    if (
        recording is None
        or not recording.upload_token_hash
        or not secrets.compare_digest(recording.upload_token_hash, digest)
    ):
        raise Forbidden()


def _check_receivable(recording):
    """Return false for an acknowledged retry, reject expired/terminal slots."""
    if recording.upload_status in {"received", "queued", "processing", "deposited"}:
        return False
    if recording.upload_status != "pending" or _utcnow() >= recording.upload_deadline:
        raise Gone("The recording upload is no longer pending.")
    return True


def _receive_recording(
    recording_id, token, stream, *, content_length=None, directory=None, connection=None
):
    """Publish a complete bounded file without locking its participant.

    An independent short transaction rechecks expiry after the stream is fully
    received. Concurrent retransmissions can publish only one file; incomplete,
    late, and losing files are removed. The caller owns no transaction here.
    """
    with Session(db.engine) as session:
        recording = session.get(Recording, recording_id)
        _authorize(recording, token)
        if not _check_receivable(recording):
            return
        max_bytes = recording.upload_max_bytes
        deadline = recording.upload_deadline
    if content_length is not None and content_length > max_bytes:
        raise RequestEntityTooLarge()

    path = None
    retained = False
    timer = None
    if connection is not None:
        # A socket timeout alone is insufficient: a WSGI read can combine many
        # successful short receives while a client trickles bytes indefinitely.
        # Closing only the read half interrupts that read while allowing a 410
        # response. Gunicorn and Werkzeug expose the owning request socket.
        def _interrupt_read():
            """Wake a blocked body reader without closing its response channel."""
            try:
                connection.shutdown(socket.SHUT_RD)
            except OSError as error:
                if error.errno not in {errno.EBADF, errno.ENOTCONN}:
                    logger.warning(
                        "Could not interrupt recording %s upload: %s",
                        recording_id,
                        error,
                    )

        timer = Timer(max(0, (deadline - _utcnow()).total_seconds()), _interrupt_read)
        timer.daemon = True
        timer.start()
    try:
        if directory is None:
            directory = _upload_directory()
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="psynet-upload-",
            dir=directory,
            delete=False,
        ) as target:
            path = Path(target.name)
            total = 0
            while True:
                if _utcnow() >= deadline:
                    raise Gone("The recording upload deadline has passed.")
                try:
                    chunk = stream.read(min(65536, max_bytes - total + 1))
                except (OSError, ClientDisconnected):
                    if _utcnow() >= deadline:
                        raise Gone(
                            "The recording upload deadline has passed."
                        ) from None
                    raise
                if _utcnow() >= deadline:
                    raise Gone("The recording upload deadline has passed.")
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RequestEntityTooLarge()
                target.write(chunk)
            if not total or (content_length is not None and total != content_length):
                raise BadRequest("The recording body is empty or incomplete.")
            target.flush()
            os.fsync(target.fileno())

        with Session(db.engine) as session, session.begin():
            recording = (
                session.query(Recording)
                .filter_by(id=recording_id)
                .with_for_update()
                .one_or_none()
            )
            _authorize(recording, token)
            if not _check_receivable(recording):
                return
            recording.input_path = str(path)
            recording.upload_received_at = _utcnow()
            recording.upload_processing_deadline = (
                recording.upload_received_at
                + timedelta(seconds=recording.upload_context["processing_timeout"])
            )
            recording.upload_status = "received"
        retained = True
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        if path is not None and not retained:
            path.unlink(missing_ok=True)


@with_transaction
def _claim_recording(recording_id):
    """Claim work once, returning plain data so file I/O holds no row locks."""
    asset = (
        Recording.query.filter_by(id=recording_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if asset is None or asset.upload_status not in {"received", "queued"}:
        return None
    if asset.upload_processing_deadline <= _utcnow():
        return None
    asset.upload_status = "processing"
    return asset.input_path, asset.storage, asset.upload_processing_deadline


def _validate_recording(path, deadline):
    """Require a WebM/Matroska video stream within the processing allowance."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "matroska",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=max(0.001, (deadline - _utcnow()).total_seconds()),
    )
    if not any(
        stream.get("codec_type") == "video"
        for stream in json.loads(result.stdout).get("streams", [])
    ):
        raise ValueError("The recording does not contain a video stream.")


def _store_recording_bytes(path, storage):
    """Reuse LocalStorage and content hashes without publishing trial callbacks.

    Copy to a unique sibling before renaming, so another asset sharing this
    content hash can never serve a partially overwritten file.
    """
    digest = sha256_file(path)
    host_path = content_object_path(digest)
    staging_host_path = f"{host_path}.upload-{uuid.uuid4().hex}"
    staging_path = Path(storage.get_file_system_path(staging_host_path)).expanduser()
    target_path = Path(storage.get_file_system_path(host_path)).expanduser()
    output = {
        "sha256_contents": digest,
        "content_id": digest,
        "md5_contents": md5_file(path),
        "host_path": host_path,
        "object_path": host_path,
        "size_mb": get_file_size_mb(path),
    }
    try:
        # The backend sets deposited on this plain snapshot, never on the live
        # asset. Only _complete_recording may publish that database transition.
        storage._receive_deposit(
            SimpleNamespace(input_path=path, is_folder=False), staging_host_path
        )
        staging_path.replace(target_path)
    finally:
        staging_path.unlink(missing_ok=True)
    return output


@with_transaction
def _complete_recording(recording_id, *, output=None, error=None):
    """Resolve one recording atomically and return its input path for cleanup."""
    from .participant import Participant
    from .trial.main import Trial

    identity = (
        db.session.query(Recording.participant_id, Recording.trial_id)
        .filter(Recording.id == recording_id)
        .first()
    )
    if identity is None:
        return None
    # Match response handling's lock order. Disk I/O happens before these locks.
    if identity.participant_id is not None:
        Participant.query.filter_by(id=identity.participant_id).with_for_update(
            of=Participant
        ).populate_existing().one()
    trial = None
    if identity.trial_id is not None:
        trial = (
            Trial.query.filter_by(id=identity.trial_id)
            .with_for_update(of=Trial)
            .populate_existing()
            .one()
        )
    asset = (
        Recording.query.filter_by(id=recording_id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if asset.upload_status not in {"pending", "received", "queued", "processing"}:
        return None
    deadline = (
        asset.upload_deadline
        if asset.upload_status == "pending"
        else asset.upload_processing_deadline
    )
    expired = _utcnow() >= deadline
    if expired:
        error = (
            "upload_timeout"
            if asset.upload_status == "pending"
            else "processing_timeout"
        )
    elif (output is None and error is None) or asset.upload_status != "processing":
        return None
    input_path = asset.input_path
    if error:
        asset.upload_status = "expired" if expired else "failed"
        asset.upload_failed_reason = error
        asset.deposited = False
        if trial is not None and not trial.failed:
            trial.fail(reason=f"recording_{error}")
    else:
        for key, value in output.items():
            setattr(asset, key, value)
        asset.deployment_id = asset.registry.deployment_id
        asset.storage.update_asset_metadata(asset)
        asset.upload_status = "deposited"
        asset.deposited = True
        if trial is None or not trial.failed:
            asset.after_deposit()
    asset.input_path = None
    return input_path


def _process_recording(recording_id):
    """Validate and store received bytes; late completion cannot revive expiry."""
    claimed = _claim_recording(recording_id)
    if claimed is None:
        return
    path, storage, deadline = claimed
    try:
        try:
            _validate_recording(path, deadline)
        except (subprocess.CalledProcessError, ValueError) as error:
            logger.warning("Invalid recording %s: %s", recording_id, error)
            _complete_recording(recording_id, error="invalid_recording")
            return
        except subprocess.TimeoutExpired:
            _complete_recording(recording_id, error="processing_timeout")
            return
        output = _store_recording_bytes(path, storage)
        _complete_recording(recording_id, output=output)
    except Exception:
        logger.warning("Processing recording %s failed.", recording_id, exc_info=True)
        _complete_recording(recording_id, error="processing_error")
    finally:
        Path(path).unlink(missing_ok=True)


@with_transaction
def _expire_recordings():
    """Expire missing or stalled recordings independently of browser activity."""
    now = _utcnow()
    ids = (
        db.session.query(Recording.id)
        .filter(
            (
                (Recording.upload_status == "pending")
                & (Recording.upload_deadline <= now)
            )
            | (
                Recording.upload_status.in_(["received", "queued", "processing"])
                & (Recording.upload_processing_deadline <= now)
            )
        )
        .all()
    )
    for (recording_id,) in ids:
        path = _complete_recording(recording_id)
        if path is not None:
            Path(path).unlink(missing_ok=True)


@with_transaction
def _queue_received_recordings():
    """Schedule processing on workers, which mount the LocalStorage volume."""
    from .process import WorkerAsyncProcess

    recordings = (
        Recording.query.filter_by(upload_status="received")
        .filter(Recording.upload_processing_deadline > _utcnow())
        .with_for_update(skip_locked=True)
        .populate_existing()
        .all()
    )
    for asset in recordings:
        asset.upload_status = "queued"
        WorkerAsyncProcess(
            _process_recording,
            arguments={"recording_id": asset.id},
            asset=asset,
            label="media_upload",
            unique=True,
        )
