"""Internal reservation and receipt of asynchronous recordings.

Reservations belong to existing Recording assets and must be created in the
accepted response transaction. Read links and upload capabilities are separate;
only a hash of the write capability is stored. The receiver authenticates before
reading bytes, streams to a private bounded file without holding database locks,
then locks only the recording row to publish complete receipt exactly once.

Receipt is not deposit: validation, storage, and trial failure policy remain
separate steps. This infrastructure is not yet enabled in recording controls.
Do not wrap the streaming route in a participant transaction or expose received
files through the asset endpoint before successful deposit.
"""

import errno
import hashlib
import math
import os
import secrets
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Timer

from dallinger import db
from sqlalchemy.orm import Session
from werkzeug.exceptions import (
    BadRequest,
    ClientDisconnected,
    Forbidden,
    Gone,
    RequestEntityTooLarge,
)

from .asset import LocalStorage
from .trial.record import Recording
from .utils import get_logger

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
    if recording.upload_status in {"received", "deposited"}:
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
        with tempfile.NamedTemporaryFile(
            prefix="psynet-upload-", dir=directory, delete=False
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
