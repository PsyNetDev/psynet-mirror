"""Manage recoverable local PsyNet deployments.

Local live deployments share one PostgreSQL database, and starting a new
deployment resets that database. This module places a small safety layer around
that behavior: a required user-facing ID groups recovery snapshots inside the
experiment directory, and snapshots are written atomically in Dallinger's
existing CSV archive format.

Operational events for local deploy and other deployment commands are recorded
in ``data/deployment-events.jsonl`` via :mod:`psynet.deployment_events`.

Snapshots are deliberately database-only and intended for recovery on the same
machine. Full PsyNet exports remain the portable format for analysis, sharing,
and migration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from rich.console import Console
from rich.prompt import IntPrompt
from rich.table import Table

from psynet.deployment_events import (
    append_deployment_event,
    file_lock,
    utc_now,
    validate_local_id,
)
from psynet.serialize import unserialize

# A stopping deployment releases the lock only once its process exits, so a
# stop-then-start sequence can briefly overlap. Wait that race out before
# reporting a genuine conflict.
DATABASE_LOCK_WAIT_SECONDS = 30.0

# Reading deployment identity must not block a launch behind a leftover backend.
DATABASE_READ_TIMEOUT_SECONDS = 10

logger = logging.getLogger("psynet")

_database_lock_guard = threading.RLock()
_database_lock_context = None
_database_lock_depth = 0


@dataclass(frozen=True)
class Snapshot:
    """Describe one local database recovery snapshot."""

    sequence: int
    path: Path
    metadata_path: Path
    created_at: str
    reason: str
    deployment_id: Optional[str]
    parent_sequence: Optional[int]
    participant_count: Optional[int]
    sha256: Optional[str]
    max_response_id: Optional[int] = None


@dataclass(frozen=True)
class DatabaseOwner:
    """Describe the experiment currently stored in the local PostgreSQL database."""

    local_id: Optional[str]
    experiment_path: Optional[Path]
    deployment_id: Optional[str]
    label: Optional[str]
    readable: bool = True
    snapshot_needed_on_shutdown: bool = True

    @property
    def managed(self) -> bool:
        """Return whether this database has managed local-deployment metadata."""
        return self.local_id is not None and self.experiment_path is not None

    @property
    def mode(self) -> Optional[str]:
        """Return the mode of the run that created this database, if recorded.

        PsyNet deployment IDs embed the mode, as in
        ``gibbs-demo__mode=debug__launch=2026-08-29--16-37-05``.
        """
        if not self.deployment_id:
            return None
        match = re.search(r"__mode=([^_]*)", self.deployment_id)
        if match is None:
            return None
        return match.group(1) or None

    @property
    def disposable(self) -> bool:
        """Return whether this database may be discarded without asking.

        ``psynet debug local`` databases are disposable by definition, and a
        database that was only ever prepared has no collected data to lose. A
        live or sandbox run, a database whose identity could not be read, or a
        database whose deployment ID does not identify its mode, is never
        treated as disposable.
        """
        if not self.readable:
            return False
        if self.mode in ("live", "sandbox"):
            return False
        if self.deployment_id and self.mode is None:
            return False
        return True


# Returned when the database holds an experiment whose identity cannot be read.
UNREADABLE_DATABASE_OWNER = DatabaseOwner(
    local_id=None,
    experiment_path=None,
    deployment_id=None,
    label=None,
    readable=False,
)


def is_managed_local_live_deployment(info: dict) -> bool:
    """Return whether ``info`` describes a managed local live deployment."""
    return bool(
        info.get("is_local_deployment")
        and info.get("mode") == "live"
        and info.get("local_id") is not None
        and info.get("local_experiment_path")
    )


def should_skip_shutdown_snapshot(owner: Optional[DatabaseOwner]) -> bool:
    """Return whether shutdown can reuse the last participant-finish snapshot.

    After a participant finishes, PsyNet snapshots the database. If nobody else
    has started since that snapshot, the termination snapshot would contain no
    new collected data.
    """
    return owner is not None and owner.managed and not owner.snapshot_needed_on_shutdown


def snapshots_directory(experiment_path: Path | str, local_id: str) -> Path:
    """Return the directory containing snapshots for ``local_id``."""
    validate_local_id(local_id)
    return Path(experiment_path).resolve() / "data" / "snapshots" / local_id


def _snapshot_from_files(path: Path) -> Snapshot:
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    created_at = metadata.get(
        "created_at",
        datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    )
    return Snapshot(
        sequence=int(path.stem),
        path=path,
        metadata_path=metadata_path,
        created_at=created_at,
        reason=metadata.get("reason", "unknown"),
        deployment_id=metadata.get("deployment_id"),
        parent_sequence=metadata.get("parent_sequence"),
        participant_count=metadata.get("participant_count"),
        sha256=metadata.get("sha256"),
        max_response_id=metadata.get("max_response_id"),
    )


def list_snapshots(experiment_path: Path | str, local_id: str) -> list[Snapshot]:
    """List completed snapshots in ascending sequence order."""
    directory = snapshots_directory(experiment_path, local_id)
    if not directory.exists():
        return []
    snapshots = []
    for path in directory.glob("*.zip"):
        if not path.stem.isdigit() or not path.with_suffix(".json").is_file():
            continue
        try:
            snapshot = _snapshot_from_files(path)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if snapshot.sha256 is not None:
            snapshots.append(snapshot)
    return sorted(snapshots, key=lambda snapshot: snapshot.sequence)


def _archive_is_valid(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None and any(
                name.endswith(".csv") for name in archive.namelist()
            )
    except (OSError, zipfile.BadZipFile):
        return False


def snapshot_is_valid(snapshot: Snapshot) -> bool:
    """Return whether a snapshot archive is readable and matches its checksum."""
    if snapshot.sha256 is None or not _archive_is_valid(snapshot.path):
        return False
    return snapshot.sha256 == _sha256(snapshot.path)


def _next_snapshot_sequence(directory: Path) -> int:
    sequences = [
        int(path.stem)
        for pattern in ("*.zip", "*.json")
        for path in directory.glob(pattern)
        if path.stem.isdigit()
    ]
    return max(sequences, default=0) + 1


def _snapshot_parent(
    snapshots: list[Snapshot],
    deployment_id: Optional[str],
    resumed_from: Optional[int],
) -> Optional[int]:
    current_launch = [
        snapshot.sequence
        for snapshot in snapshots
        if deployment_id is not None and snapshot.deployment_id == deployment_id
    ]
    if current_launch:
        return max(current_launch)
    return resumed_from


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomically(path: Path, content: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.partial")
    try:
        temporary.write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_snapshot(
    experiment_path: Path | str,
    local_id: str,
    reason: str,
    deployment_id: Optional[str],
    resumed_from: Optional[int] = None,
    *,
    exporter: Optional[Callable[[Path], Optional[int]]] = None,
) -> Snapshot:
    """Create and record one atomic database recovery snapshot."""
    validate_local_id(local_id)
    root = Path(experiment_path).resolve()
    directory = snapshots_directory(root, local_id)
    directory.mkdir(parents=True, exist_ok=True)
    exporter = exporter or export_database_snapshot

    with file_lock(directory / ".snapshot.lock"):
        snapshots = list_snapshots(root, local_id)
        sequence = _next_snapshot_sequence(directory)
        stem = f"{sequence:06d}"
        path = directory / f"{stem}.zip"
        metadata_path = directory / f"{stem}.json"
        temporary = directory / f".{stem}.{uuid4().hex}.zip.partial"
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        parent_sequence = _snapshot_parent(snapshots, deployment_id, resumed_from)
        started_at = datetime.now(timezone.utc)
        try:
            participant_count = exporter(temporary)
            if not _archive_is_valid(temporary):
                raise RuntimeError("Snapshot exporter produced an invalid archive.")
            checksum = _sha256(temporary)
            os.replace(temporary, path)
            path.chmod(0o600)
            max_response_id = None
            if exporter is export_database_snapshot:
                max_response_id = read_response_watermark()
            metadata = {
                "schema_version": 1,
                "id": local_id,
                "sequence": sequence,
                "created_at": utc_now(),
                "reason": reason,
                "deployment_id": deployment_id,
                "parent_sequence": parent_sequence,
                "participant_count": participant_count,
                "max_response_id": max_response_id,
                "sha256": checksum,
            }
            _write_json_atomically(metadata_path, metadata)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            append_deployment_event(
                root,
                "snapshot.failed",
                local_id,
                reason=reason,
                deployment_id=deployment_id,
                error=str(error),
            )
            raise

    duration = (datetime.now(timezone.utc) - started_at).total_seconds()
    append_deployment_event(
        root,
        "snapshot.succeeded",
        local_id,
        sequence=sequence,
        reason=reason,
        deployment_id=deployment_id,
        parent_sequence=parent_sequence,
        participant_count=participant_count,
        sha256=checksum,
        max_response_id=max_response_id,
        duration_seconds=round(duration, 3),
    )
    return _snapshot_from_files(path)


def choose_snapshot(
    experiment_path: Path | str,
    local_id: str,
    requested: Optional[str] = None,
    *,
    console: Optional[Console] = None,
) -> Optional[Snapshot]:
    """Select a snapshot explicitly or interactively, defaulting to the latest."""
    snapshots = list_snapshots(experiment_path, local_id)
    if not snapshots:
        if requested is not None:
            raise ValueError(
                f"Snapshot {requested} does not exist for ID '{local_id}'."
            )
        return None

    by_sequence = {snapshot.sequence: snapshot for snapshot in snapshots}
    selected = None
    if requested is not None:
        if requested == "latest":
            selected = snapshots[-1]
        else:
            try:
                sequence = int(requested)
            except ValueError as error:
                raise ValueError(
                    "Snapshot must be 'latest' or a sequence number."
                ) from error
            if sequence not in by_sequence:
                raise ValueError(
                    f"Snapshot {sequence} does not exist for ID '{local_id}'."
                )
            selected = by_sequence[sequence]
    elif not sys.stdin.isatty():
        selected = snapshots[-1]
    else:
        console = console or Console()
        recent = list(reversed(snapshots[-10:]))
        table = Table(title=f"Snapshots for local deployment '{local_id}'")
        table.add_column("Choice", justify="right")
        table.add_column("Snapshot")
        table.add_column("Created")
        table.add_column("Reason")
        table.add_column("Participants", justify="right")
        for choice, snapshot in enumerate(recent, start=1):
            table.add_row(
                str(choice),
                f"{snapshot.sequence:06d}",
                snapshot.created_at,
                snapshot.reason,
                ""
                if snapshot.participant_count is None
                else str(snapshot.participant_count),
            )
        console.print(table)
        choice = IntPrompt.ask(
            "Resume from",
            choices=[str(index) for index in range(1, len(recent) + 1)],
            default=1,
            console=console,
        )
        selected = recent[choice - 1]

    if not snapshot_is_valid(selected):
        raise ValueError(
            f"Snapshot {selected.sequence} for ID '{local_id}' is corrupt or incomplete."
        )
    return selected


def export_database_snapshot(destination: Path, db_url: Optional[str] = None) -> int:
    """Write a consistent Dallinger-compatible CSV database archive."""
    import psycopg2
    from psycopg2 import sql

    if db_url is None:
        from dallinger import db

        db_url = db.db_url

    connection = psycopg2.connect(dsn=db_url)
    try:
        connection.set_session(
            isolation_level="REPEATABLE READ",
            readonly=True,
            autocommit=False,
        )
        cursor = connection.cursor()
        cursor.execute(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = [row[0] for row in cursor.fetchall()]
        if "experiment" not in tables:
            raise RuntimeError(
                "The local database does not contain a PsyNet experiment."
            )

        participant_count = 0
        if "participant" in tables:
            cursor.execute("SELECT count(*) FROM participant")
            participant_count = cursor.fetchone()[0]

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_directory = root / "data"
            data_directory.mkdir()
            for table in tables:
                path = data_directory / f"{table}.csv"
                statement = sql.SQL("COPY {} TO STDOUT WITH CSV HEADER").format(
                    sql.Identifier(table)
                )
                with path.open("w", encoding="utf-8", newline="") as file:
                    cursor.copy_expert(statement.as_string(connection), file)
            (root / "experiment_id.md").write_text("local", encoding="utf-8")
            with zipfile.ZipFile(
                destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
            ) as archive:
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(root))
        connection.rollback()
        return participant_count
    finally:
        connection.close()


def read_response_watermark(db_url: Optional[str] = None) -> Optional[int]:
    """Return the highest ``response.id``, or ``0`` if the table is empty.

    Returns ``None`` when the watermark cannot be read, so callers can fail
    closed instead of treating an unknown database as unchanged.
    """
    import psycopg2

    if db_url is None:
        from dallinger import db

        db_url = db.db_url
    try:
        connection = psycopg2.connect(
            dsn=db_url,
            connect_timeout=DATABASE_READ_TIMEOUT_SECONDS,
            options=(
                f"-c statement_timeout={int(DATABASE_READ_TIMEOUT_SECONDS * 1000)} "
                f"-c lock_timeout={int(DATABASE_READ_TIMEOUT_SECONDS * 1000)}"
            ),
        )
    except Exception:
        logger.warning("Could not read response watermark from the local database.")
        return None
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT COALESCE(MAX(id), 0) FROM response")
        except psycopg2.errors.UndefinedTable:
            connection.rollback()
            return 0
        except (psycopg2.errors.QueryCanceled, psycopg2.errors.LockNotAvailable):
            connection.rollback()
            logger.warning("Timed out reading response watermark.")
            return None
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        logger.warning("Could not read response watermark from the local database.")
        return None
    finally:
        connection.close()


def read_database_owner(db_url: Optional[str] = None) -> Optional[DatabaseOwner]:
    """Read managed local-deployment identity from the current PostgreSQL database.

    Returns ``None`` when the database holds no experiment, and
    ``UNREADABLE_DATABASE_OWNER`` when one is present but its identity cannot be
    read. This runs before every local launch, so a leftover backend holding
    locks, or unexpected table contents, must not hang or crash the launch;
    callers treat an unreadable database as unmanaged, which keeps managed
    deployments from overwriting it without ``--adopt-existing``.
    """
    import psycopg2

    if db_url is None:
        from dallinger import db

        db_url = db.db_url
    connection = psycopg2.connect(
        dsn=db_url,
        connect_timeout=DATABASE_READ_TIMEOUT_SECONDS,
        options=(
            f"-c statement_timeout={int(DATABASE_READ_TIMEOUT_SECONDS * 1000)} "
            f"-c lock_timeout={int(DATABASE_READ_TIMEOUT_SECONDS * 1000)}"
        ),
    )
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT vars FROM experiment")
        except psycopg2.errors.UndefinedTable:
            connection.rollback()
            return None
        except (psycopg2.errors.QueryCanceled, psycopg2.errors.LockNotAvailable):
            connection.rollback()
            logger.warning(
                "Timed out reading local deployment metadata; another process may "
                "still be using the local database. Treating it as unmanaged."
            )
            return UNREADABLE_DATABASE_OWNER
        rows = cursor.fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            logger.warning(
                "Expected one row in the experiment table, found %d. "
                "Treating the local database as unmanaged.",
                len(rows),
            )
            return UNREADABLE_DATABASE_OWNER
        try:
            variables = unserialize(rows[0][0])
        except Exception as error:
            logger.warning(
                "Could not read local deployment metadata (%s). "
                "Treating the local database as unmanaged.",
                error,
            )
            return UNREADABLE_DATABASE_OWNER
        if not isinstance(variables, dict):
            logger.warning(
                "Local deployment metadata has unexpected type %s. "
                "Treating the local database as unmanaged.",
                type(variables).__name__,
            )
            return UNREADABLE_DATABASE_OWNER
        experiment_path = variables.get("local_experiment_path")
        needed = variables.get("local_snapshot_needed_on_shutdown")
        return DatabaseOwner(
            local_id=variables.get("local_deployment_id"),
            experiment_path=Path(experiment_path).resolve()
            if experiment_path
            else None,
            deployment_id=variables.get("deployment_id"),
            label=variables.get("label"),
            snapshot_needed_on_shutdown=True if needed is None else bool(needed),
        )
    finally:
        connection.close()


def local_database_lock_path() -> Path:
    """Return the lock file that serializes local PostgreSQL access.

    Local deployments share one PostgreSQL database per machine, including
    across OS users, so the lock lives in ``/tmp`` rather than a home
    directory. Tests and unusual hosts may override the path with
    ``PSYNET_LOCAL_DATABASE_LOCK``.
    """
    override = os.environ.get("PSYNET_LOCAL_DATABASE_LOCK")
    if override:
        return Path(override)
    return Path("/tmp/psynet-local-deployment.lock")


def _read_lock_holder(path: Path) -> Optional[dict]:
    """Return the process currently described by ``path``, if readable."""
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        holder = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(holder, dict):
        return None
    return holder


def concurrent_deployment_error(lock_path: Optional[Path] = None) -> RuntimeError:
    """Explain that another local experiment must be stopped before starting this one."""
    message = (
        "Another local PsyNet experiment is already running. "
        "Stop it first, then try again."
    )
    holder = _read_lock_holder(lock_path or local_database_lock_path())
    if holder:
        details = []
        if holder.get("id"):
            details.append(f"id {holder['id']}")
        if holder.get("experiment_path"):
            details.append(f"directory {holder['experiment_path']}")
        if holder.get("pid") is not None:
            details.append(f"pid {holder['pid']}")
        if details:
            message += " Running experiment: " + "; ".join(details) + "."
    return RuntimeError(message)


def _acquire_lock_file(path: Path, wait_seconds: float):
    """Acquire ``path``, waiting out a lock that a stopping deployment still holds."""
    deadline = time.monotonic() + wait_seconds
    waited = False
    while True:
        lock_context = file_lock(path, blocking=False)
        try:
            return lock_context, lock_context.__enter__()
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            if not waited:
                waited = True
                logger.info(
                    "The local database is locked by another PsyNet process; "
                    "waiting up to %.0fs in case it is shutting down.",
                    wait_seconds,
                )
            time.sleep(0.5)


@contextmanager
def local_database_lock(
    experiment_path: Path | str | None = None,
    local_id: Optional[str] = None,
    *,
    wait_seconds: float = DATABASE_LOCK_WAIT_SECONDS,
):
    """Serialize destructive access to the shared local PostgreSQL database."""
    global _database_lock_context, _database_lock_depth

    if local_id is not None:
        validate_local_id(local_id)
    path = local_database_lock_path()
    outermost = False
    _database_lock_guard.acquire()
    try:
        if _database_lock_depth == 0:
            lock_context, file = _acquire_lock_file(path, wait_seconds)
            _database_lock_context = lock_context
            outermost = True
        _database_lock_depth += 1
        try:
            if outermost:
                file.seek(0)
                file.truncate()
                file.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "experiment_path": (
                                str(Path(experiment_path).resolve())
                                if experiment_path is not None
                                else None
                            ),
                            "id": local_id,
                        }
                    )
                )
                file.flush()
            yield
        finally:
            if _database_lock_depth > 0:
                _database_lock_depth -= 1
            if _database_lock_depth == 0 and _database_lock_context is not None:
                lock_context = _database_lock_context
                _database_lock_context = None
                lock_context.__exit__(None, None, None)
    except BlockingIOError as error:
        raise concurrent_deployment_error(path) from error
    finally:
        _database_lock_guard.release()


def _describe_owner(owner: DatabaseOwner) -> str:
    """Return a parenthesised description of ``owner``, or an empty string."""
    details = []
    if owner.label:
        details.append(f"label {owner.label!r}")
    if owner.mode:
        details.append(f"mode {owner.mode}")
    if not owner.readable:
        details.append("identity unreadable")
    return f" ({', '.join(details)})" if details else ""


def latest_snapshot_covers_owner(
    owner: DatabaseOwner, latest: Optional[Snapshot]
) -> bool:
    """Return whether ``latest`` already preserves ``owner``'s collected data."""
    if (
        latest is None
        or not snapshot_is_valid(latest)
        or latest.deployment_id != owner.deployment_id
    ):
        return False
    if latest.max_response_id is not None:
        current = read_response_watermark()
        if current is not None and current > latest.max_response_id:
            return False
    if latest.reason in {"shutdown", "recovery-before-reset", "adopt-existing"}:
        return True
    # A finish snapshot is terminal only when nobody has started since.
    return (
        latest.reason == "participant_finished"
        and not owner.snapshot_needed_on_shutdown
    )


def protect_existing_database(
    requested_experiment_path: Path | str,
    requested_local_id: str,
    *,
    adopt_existing: bool = False,
    ignore_unmanaged: bool = False,
) -> Optional[Snapshot]:
    """Snapshot unsaved database state before a destructive local launch."""
    owner = read_database_owner()
    if owner is None:
        return None

    requested_path = Path(requested_experiment_path).resolve()
    if not owner.managed:
        # Unreadable identity may be a locked managed deployment; never discard
        # it just because this path ignores ordinary unmanaged databases.
        # ``ignore_unmanaged`` only skips disposable debug/prepare leftovers.
        if ignore_unmanaged and owner.disposable:
            return None
        if owner.disposable and not adopt_existing:
            Console().print(
                "Discarding the local database left by a previous "
                f"{owner.mode or 'preparation'} run."
            )
            return None
        if not adopt_existing:
            raise RuntimeError(
                "The local database contains an unmanaged PsyNet experiment"
                f"{_describe_owner(owner)}. Re-run with --adopt-existing to save "
                "it under the requested ID."
            )
        append_deployment_event(
            requested_path,
            "database.adopted",
            requested_local_id,
            previous_label=owner.label,
        )
        return create_snapshot(
            requested_path,
            requested_local_id,
            reason="adopt-existing",
            deployment_id=owner.deployment_id,
        )

    if not owner.experiment_path.exists():
        raise RuntimeError(
            "The local database belongs to an experiment directory that no longer "
            f"exists: {owner.experiment_path}"
        )

    snapshots = list_snapshots(owner.experiment_path, owner.local_id)
    latest = snapshots[-1] if snapshots else None
    if latest_snapshot_covers_owner(owner, latest):
        return None

    return create_snapshot(
        owner.experiment_path,
        owner.local_id,
        reason="recovery-before-reset",
        deployment_id=owner.deployment_id,
    )
