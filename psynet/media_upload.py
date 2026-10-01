"""Internal reservation and receipt of asynchronous recordings.

Reservations belong to existing Recording assets and must be created in the
accepted response transaction. Read links and upload capabilities are separate;
only a hash of the write capability is stored. The receiver authenticates before
reading bytes, takes a cross-process file lock, and streams to a private bounded
file without holding database locks. It then locks only the recording row to
publish complete receipt exactly once.

Receipt is not deposit: a worker validates and stores bytes before a short
transaction publishes success. A poller expires overdue recordings even when
the browser has closed. In-place LocalStorage video controls use this transport.
Do not wrap the streaming route in a participant transaction or expose received
files through the asset endpoint before successful deposit.
"""

import copy
import errno
import fcntl
import hashlib
import hmac
import math
import os
import secrets
import socket
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
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
    TooManyRequests,
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


def _recording_resolution_deadline(recording):
    """Return the existing deadline including any remaining processing allowance."""
    if recording.upload_status == "pending":
        return recording.upload_deadline + timedelta(
            seconds=recording.upload_context["processing_timeout"]
        )
    return recording.upload_processing_deadline


def _recording_wait_timeout(participant_id, default_timeout=20.0, *, trial_id=None):
    """Keep dependent waits alive through existing recording deadlines.

    Compute once on entering a wait. Pending uploads may receive their bytes at
    the upload deadline and then use their processing allowance. Retain the
    ordinary wait budget afterwards for analysis and clock polling. This never
    extends a recording's own deadline or changes its success requirements.
    """
    from .trial.main import Trial

    if default_timeout is None:
        return None
    query = (
        db.session.query(
            Recording.upload_status,
            Recording.upload_deadline,
            Recording.upload_processing_deadline,
            Recording.upload_context,
        )
        .join(Trial, Recording.trial_id == Trial.id)
        .filter(
            Recording.participant_id == participant_id,
            Recording.required_for_trial,
            ~Trial.failed,
            Recording.upload_status.in_(
                ["pending", "received", "queued", "processing"]
            ),
        )
    )
    if trial_id is not None:
        query = query.filter(Recording.trial_id == trial_id)
    now = _utcnow()
    remaining = 0.0
    for recording in query:
        deadline = _recording_resolution_deadline(recording)
        remaining = max(remaining, (deadline - now).total_seconds())
    return default_timeout + remaining


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
    role="answer",
    required_for_trial=True,
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
    asset.recording_role = role
    asset.required_for_trial = required_for_trial
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
        "page_label": response.question,
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


@contextmanager
def _receipt_lock(directory, recording_id):
    """Serialize receipt and cleanup across processes on the shared volume.

    Keep the small lock file in place: unlinking a live lock could allow another
    process to lock a different inode. OS process exit releases the lock itself.
    """
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        directory / f".psynet-upload-{recording_id}.lock", os.O_CREAT | os.O_RDWR, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TooManyRequests(
                "This recording already has an active upload."
            ) from None
        yield
    finally:
        os.close(descriptor)


def _receive_recording(
    recording_id, token, stream, *, content_length=None, directory=None, connection=None
):
    """Authenticate before taking exclusive receipt ownership or reading bytes."""
    with Session(db.engine) as session:
        recording = session.get(Recording, recording_id)
        _authorize(recording, token)
        if not _check_receivable(recording):
            return
    directory = _upload_directory() if directory is None else Path(directory)
    with _receipt_lock(directory, recording_id):
        return _receive_recording_body(
            recording_id,
            token,
            stream,
            content_length=content_length,
            directory=directory,
            connection=connection,
        )


def _receive_recording_body(
    recording_id, token, stream, *, directory, content_length=None, connection=None
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

    # A previous receiver may have died before publishing receipt. Ownership of
    # this reservation is exclusive, so discard its abandoned partials on retry.
    for abandoned in Path(directory).glob(f"psynet-upload-{recording_id}-*"):
        abandoned.unlink(missing_ok=True)

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
        with tempfile.NamedTemporaryFile(
            prefix=f"psynet-upload-{recording_id}-",
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
    """Decode video within the processing budget and require nonempty output.

    A declared stream can be just a truncated header. Decode all video frames,
    failing on decoding errors, and scale output to one gray byte per frame so
    validation does not retain full-resolution frames in memory.
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-xerror",
            "-threads",
            "1",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "matroska",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "scale=1:1",
            "-pix_fmt",
            "gray",
            "-threads",
            "1",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=max(0.001, (deadline - _utcnow()).total_seconds()),
    )
    if not result.stdout:
        raise ValueError("The recording contains no decodable video frames.")


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
            (asset.upload_context.get("unavailable_reason") or "upload_timeout")
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
        if asset.required_for_trial and trial is not None and not trial.failed:
            trial.fail(reason=f"recording_{error}")
    else:
        for key, value in output.items():
            setattr(asset, key, value)
        asset.deployment_id = asset.registry.deployment_id
        asset.storage.update_asset_metadata(asset)
        asset.upload_status = "deposited"
        asset.deposited = True
        if asset.required_for_trial and (trial is None or not trial.failed):
            if asset.recording_role == "background":
                if trial is not None:
                    trial.check_if_can_mark_as_finalized()
            else:
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


def _clean_abandoned_receipts():
    """Remove crashed receivers' files once no live reservation needs them."""
    directory = _upload_directory()
    if not directory.exists():
        return
    for path in directory.glob("psynet-upload-*"):
        parts = path.name.split("-", 3)
        if len(parts) != 4 or not parts[2].isdigit():
            continue
        recording_id = int(parts[2])
        try:
            with _receipt_lock(directory, recording_id):
                with Session(db.engine) as session:
                    asset = session.get(Recording, recording_id)
                    abandoned = asset is None or asset.upload_status in {
                        "expired",
                        "failed",
                        "deposited",
                    }
                    if asset is not None and asset.upload_status == "pending":
                        abandoned = _utcnow() >= asset.upload_deadline
                    if abandoned:
                        path.unlink(missing_ok=True)
        except TooManyRequests:
            # An active receiver owns its file until its deadline interrupts it.
            continue


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
    _clean_abandoned_receipts()


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


def _recovery_digest(secret):
    """Validate a browser-only recovery secret without storing its plaintext."""
    if not isinstance(secret, str) or len(secret) != 64:
        raise ValueError("Invalid recording recovery secret.")
    try:
        value = bytes.fromhex(secret)
    except ValueError:
        raise ValueError("Invalid recording recovery secret.") from None
    if len(value) != 32:
        raise ValueError("Invalid recording recovery secret.")
    return hashlib.sha256(value).hexdigest()


def _recovery_upload_token(secret, recording_id):
    """Derive a per-recording capability from an unpersisted browser secret."""
    return hmac.new(
        bytes.fromhex(secret),
        f"recording-upload:{recording_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _save_recording_receipt(response, participant, page_uuid, secret, payload):
    """Atomically retain accepted navigation and token-free upload descriptors."""
    cached = copy.deepcopy(payload)
    for receipt, saved in zip(
        payload["recording_uploads"], cached["recording_uploads"]
    ):
        asset = db.session.get(Recording, int(receipt["id"]))
        token = _recovery_upload_token(secret, asset.id)
        asset.upload_token_hash = hashlib.sha256(token.encode()).hexdigest()
        receipt["token"] = token
        saved.pop("token")
    response.recording_receipt_hash = _recovery_digest(secret)
    response.recording_receipt = {
        "page_uuid": page_uuid,
        "next_page_uuid": participant.page_uuid,
        "payload": cached,
    }


def _refresh_recording_receipt(response_id, participant, payload):
    """Retain the final successor after barrier settlement and page preparation.

    Receipt capabilities were assigned atomically with answer acceptance. Only
    navigation metadata changes here; upload deadlines and tokens stay fixed.
    """
    from .timeline import Response

    response = db.session.get(Response, response_id)
    cached = copy.deepcopy(payload)
    for upload in cached["recording_uploads"]:
        upload.pop("token", None)
    response.recording_receipt = {
        **response.recording_receipt,
        "next_page_uuid": participant.page_uuid,
        "payload": cached,
    }


def _recover_recording_receipt(participant, page_uuid, secret):
    """Replay only this participant's accepted page while its successor is current.

    The caller holds the participant lock, so a retry waits for the original
    transaction. Replaying never reruns validation, completion, or navigation.
    Original timestamps preserve the upload deadline across network retries.
    """
    from .timeline import Response

    response = Response.query.filter_by(
        participant_id=participant.id, recording_receipt_hash=_recovery_digest(secret)
    ).one_or_none()
    if response is None:
        return None
    saved = response.recording_receipt
    if (
        saved["page_uuid"] != page_uuid
        or saved["next_page_uuid"] != participant.page_uuid
    ):
        return False
    payload = copy.deepcopy(saved["payload"])
    for receipt in payload["recording_uploads"]:
        receipt["token"] = _recovery_upload_token(secret, receipt["id"])
    return payload
