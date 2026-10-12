"""Start every performance test from the same database.

``psynet performance-test local --reset-database`` resets the experiment's
database before each test of a suite, so that the tests of ``--n-bots auto``
compare load rather than amounts of data. :class:`DatabaseReset` is the
suite's ``before_test`` hook (see :class:`psynet.perf_test.PerformanceSuite`).

Before the first test it takes a snapshot of the database with ``CREATE
DATABASE ... TEMPLATE``, a file-level copy that keeps sequences, indexes and
table bloat; before each later test it copies the snapshot to a new database
and swaps that in for the experiment database. PostgreSQL only copies a
database that nobody is connected to, so the hook stops the experiment
server, terminates the connections that remain, and starts the server again
afterwards. Restarting also empties the server's in-memory caches, some of
which hold row IDs. The hook also deletes the RQ job keys from Redis, because
jobs refer to rows by ID, but keeps the other keys, such as the launch flags
without which the server would launch the experiment again.

With ``--prefill-participants``, bots first add data, and the snapshot is
kept as a pre-fill cache under a name made from the experiment code, the
PsyNet version and the pre-fill settings (see :func:`prefill_snapshot_name`),
so that a later run with the same code and settings starts from it instead
of pre-filling again.

Design constraints:

- Only the experiment database, the copy that replaces it, and snapshots
  that this module names are ever dropped, and only on this computer's
  PostgreSQL server (see :func:`check_resettable_database`).
- A reset and the replacement of a kept snapshot are both a swap (see
  :func:`_swap_in_copy`): the copy is complete before the old database is
  dropped. If renaming the copy fails after that, :meth:`DatabaseReset.close`
  renames it, and a snapshot is only dropped while the experiment database
  exists.
- If the PostgreSQL role may not create databases, the snapshot is a
  ``pg_dump`` archive in ``.deploy/performance_snapshots`` of the experiment,
  which each reset restores in a single transaction. That is slower, and
  leaves the tables freshly packed.
- Files that tests add to the asset storage remain after a reset; only the
  rows that refer to them go.

The class doesn't know how the server runs: callers pass functions that stop
and start it (see :mod:`psynet.perf_local_server`), so that a remote
deployment can reuse it with its own functions and, by overriding
:meth:`DatabaseReset._connect`, its own database access.
"""

import datetime
import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from psynet.isolated_environment import (
    drop_database,
    replacement_name,
    terminate_connections,
)
from psynet.log import warning

logger = logging.getLogger(__name__)

SNAPSHOT_DIRECTORY = Path(".deploy") / "performance_snapshots"
# Async processes left from pre-filling would never run after a reset,
# because the reset deletes their RQ jobs.
_ASYNC_DRAIN_TIMEOUT_S = 3600
_IN_USE_ATTEMPTS = 10
_INSUFFICIENT_PRIVILEGE = "42501"
_OBJECT_IN_USE = "55006"
_MAX_NAME_LENGTH = 63
_PREFILL_NAME = re.compile(r"psynet_prefill_(?P<code>[0-9a-f]{12})_n\d+_k\d+")
_SYSTEM_DATABASES = {"postgres", "template0", "template1"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SETTINGS_FILES = ("config.txt", "requirements.txt", "constraints.txt")


def check_resettable_database(database_url):
    """Return ``"<database> on <host>"``, or raise if ``--reset-database`` must not drop it.

    Raises
    ------
    ValueError
        If the database is a PostgreSQL system database or isn't on this
        computer. A local database outside the isolated test environment,
        as with ``PSYNET_TEST_ENVIRONMENT=shared``, is allowed.
    """
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    host = url.query.get("host") or url.host or "local socket"
    if not url.database or url.database in _SYSTEM_DATABASES:
        raise ValueError(f"Refusing to reset the database {url.database!r}.")
    if not (host in _LOCAL_HOSTS or host == "local socket" or host.startswith("/")):
        raise ValueError(
            f"Refusing to reset the database {url.database} on {host}: "
            "--reset-database only resets a database on this computer."
        )
    return f"{url.database} on {host}"


def experiment_code_key():
    """Return a short hash of the experiment's files and the PsyNet and Dallinger versions.

    The files are those that a deployment would copy, without the ones Git
    ignores, such as generated boilerplate, plus the ``_SETTINGS_FILES``
    that exist: deployments regenerate those, so the deployment plan leaves
    them out, but local runs use them as they are.

    Raises
    ------
    ValueError
        If the experiment has no ``deploy.toml``.
    """
    import dallinger.version

    import psynet
    from psynet.deployment_info import authored_deployment_files

    files = authored_deployment_files()
    if files is None:
        raise ValueError(
            "Caching pre-fill snapshots needs the experiment's deploy.toml."
        )
    listed = {destination for destination, _ in files}
    files += [(name, name) for name in _SETTINGS_FILES if name not in listed]
    digest = hashlib.sha256(
        f"{psynet.__version__}\0{dallinger.version.__version__}".encode()
    )
    for destination, source in sorted(files):
        if not os.path.isfile(source):
            continue
        digest.update(f"\0{destination}\0".encode())
        with open(source, "rb") as f:
            while chunk := f.read(1 << 20):
                digest.update(chunk)
    return digest.hexdigest()[:12]


def prefill_snapshot_name(code_key, n_participants, n_bots):
    """Return the name of the pre-fill snapshot for these code and settings."""
    return f"psynet_prefill_{code_key}_n{n_participants}_k{n_bots}"


def snapshot_code_key(snapshot):
    """Return the code key in a pre-fill snapshot's name, or ``None``."""
    match = _PREFILL_NAME.fullmatch(_snapshot_stem(snapshot))
    return match["code"] if match else None


def find_snapshot(name, database_url, directory=SNAPSHOT_DIRECTORY):
    """Return snapshot database ``name``, or its ``pg_dump`` archive, or ``None``."""
    with _maintenance_cursor(database_url) as cursor:
        if _database_exists(cursor, name):
            return name
    archive = Path(directory) / f"{name}.dump"
    return str(archive) if archive.is_file() else None


def check_snapshot(snapshot, database_url):
    """Raise ``ValueError`` unless ``snapshot`` is a pre-fill snapshot or archive that exists."""
    if snapshot.endswith(".dump"):
        if not os.path.isfile(snapshot):
            raise ValueError(f"No pg_dump archive {snapshot}.")
        return
    if snapshot_code_key(snapshot) is None:
        raise ValueError(
            f"{snapshot} is not a pre-fill snapshot; list them with "
            "'psynet performance-test snapshots'."
        )
    with _maintenance_cursor(database_url) as cursor:
        if not _database_exists(cursor, snapshot):
            raise ValueError(f"No snapshot database {snapshot}.")


def list_snapshots(database_url, directory=SNAPSHOT_DIRECTORY):
    """Return ``(name, size_bytes, description)`` for each pre-fill snapshot.

    The snapshots are the databases on the server, which all experiments
    share, and the ``pg_dump`` archives in ``directory``.
    """
    with _maintenance_cursor(database_url) as cursor:
        cursor.execute(
            "SELECT datname, pg_database_size(oid), "
            "shobj_description(oid, 'pg_database') FROM pg_database "
            "WHERE datname LIKE 'psynet\\_prefill\\_%' ORDER BY datname"
        )
        snapshots = [row for row in cursor.fetchall() if snapshot_code_key(row[0])]
    for archive in sorted(Path(directory).glob("psynet_prefill_*.dump")):
        if snapshot_code_key(archive.name):
            snapshots.append((str(archive), archive.stat().st_size, None))
    return snapshots


def drop_snapshot(snapshot, database_url):
    """Drop a pre-fill snapshot database, or delete its ``pg_dump`` archive."""
    if snapshot_code_key(snapshot) is None:
        raise ValueError(f"{snapshot} is not a pre-fill snapshot.")
    if snapshot.endswith(".dump"):
        os.remove(snapshot)
        return
    with _maintenance_cursor(database_url) as cursor:
        drop_database(cursor, snapshot)


class DatabaseReset:
    """Reset the experiment database to a snapshot before each call.

    The first call adds any pre-fill data, waits for async processes to
    finish, and takes the snapshot; with ``from_snapshot`` it restores that
    snapshot instead. Every later call restores the snapshot. Each call
    stops the server first and always starts it again.

    Parameters
    ----------
    stop_server, start_server : callable
        Stop the experiment server's processes; start them again and wait
        until the server answers.
    prefill : callable, optional
        Called with the server running before the snapshot is taken, to add
        data (see :func:`psynet.perf_test.prefill_database`).
    from_snapshot : str, optional
        A snapshot to start from: a database name, or the path of a
        ``pg_dump`` archive. It is only read.
    keep_as : str, optional
        Take the snapshot under this pre-fill snapshot name (see
        :func:`prefill_snapshot_name`), replacing any snapshot of that name,
        and keep it. Otherwise the snapshot is dropped at :meth:`close`.
    description : str, optional
        Stored as the comment of a kept snapshot database.
    snapshot_directory : str, optional
        Where to write a ``pg_dump`` archive if the role may not create
        databases.
    database_url : str, optional
        The experiment database. Defaults to Dallinger's.
    """

    def __init__(
        self,
        stop_server,
        start_server,
        *,
        prefill=None,
        from_snapshot=None,
        keep_as=None,
        description=None,
        snapshot_directory=SNAPSHOT_DIRECTORY,
        database_url=None,
    ):
        if keep_as is not None and snapshot_code_key(keep_as) is None:
            raise ValueError(f"{keep_as} is not a pre-fill snapshot name.")
        if database_url is None:
            from dallinger import db

            database_url = db.engine.url.render_as_string(hide_password=False)
        self.database_url = database_url
        self.database = urlsplit(database_url).path.lstrip("/")
        self.snapshot = from_snapshot
        # Rows in each growing table of the snapshot, once restored or taken.
        self.snapshot_rows = None
        self._stop_server = stop_server
        self._start_server = start_server
        self._prefill = prefill
        self._keep_as = keep_as
        self._description = description
        self._snapshot_directory = Path(snapshot_directory)
        self._owns_snapshot = False
        self._disk_space_unknown = False
        # Whether the pre-fill for ``keep_as`` and its async processes finished.
        self._prefilled = False

    def __call__(self):
        """Take or restore the snapshot, with the server stopped meanwhile.

        The server starts again afterwards. If a restore fails, other than
        by an interrupt, the server only starts again if the experiment
        database exists; after a failed snapshot it stays stopped. The error
        propagates, and :meth:`close` then repairs the database if it can.
        """
        from psynet.db import release_local_database_connections

        taking = self.snapshot is None
        if taking:
            if self._prefill is not None:
                self._prefill()
            self._wait_for_async_processes()
            self._prefilled = self._keep_as is not None
        logger.info("")
        logger.info(
            "Taking a snapshot of the database..."
            if taking
            else f"Resetting the database to {self.snapshot}..."
        )
        self._stop_server()
        try:
            release_local_database_connections()
            if taking:
                self._take_snapshot()
            else:
                self._restore()
            self._clear_job_queues()
        except BaseException as error:
            if not taking and not isinstance(error, KeyboardInterrupt):
                self._restart_after_failure()
            raise
        self._start_server()
        if self.snapshot_rows is None:
            self.snapshot_rows = self._count_rows()
            rows = ", ".join(f"{t} {n:,}" for t, n in self.snapshot_rows.items())
            logger.info(f"Snapshot {self.snapshot}: {rows} rows.")

    def _restart_after_failure(self):
        """Start the server after a failed reset if its database exists.

        A failure to start is only logged, so that the reset's own error is
        the one that propagates.
        """
        try:
            with self._connect() as cursor:
                present = _database_exists(cursor, self.database)
            if present:
                self._start_server()
            else:
                logger.warning(
                    warning(
                        f"The experiment server stays stopped, because the reset "
                        f"failed after dropping {self.database}."
                    )
                )
        except Exception:
            logger.exception("Could not restart the experiment server.")

    def close(self):
        """Repair the database after a failed reset, then drop a snapshot taken here.

        A copy left by a reset that failed after dropping the experiment
        database becomes the experiment database again. A pre-fill whose
        snapshot was interrupted is kept now. The snapshot is kept if the
        experiment database doesn't exist.
        """
        import psycopg2

        try:
            with self._connect() as cursor:
                present = _recover_database(cursor, self.database)
                if present and self._prefilled and self.snapshot is None:
                    self._take_snapshot()
                if not present:
                    logger.warning(
                        warning(
                            f"Kept the snapshot {self.snapshot}, because "
                            f"{self.database} no longer exists."
                        )
                    )
                    return
                if self._owns_snapshot and not self.snapshot.endswith(".dump"):
                    drop_database(cursor, self.snapshot)
        except psycopg2.Error as e:
            logger.warning(
                warning(
                    f"Could not finish resetting the database ({e}). Check that "
                    f"{self.database} exists, and drop the snapshot with "
                    f"'dropdb {self.snapshot}'."
                )
            )
            return
        if self._owns_snapshot and self.snapshot.endswith(".dump"):
            os.remove(self.snapshot)

    @contextmanager
    def _connect(self):
        """Yield an autocommit cursor on the server's maintenance database."""
        with _maintenance_cursor(self.database_url) as cursor:
            yield cursor

    def _wait_for_async_processes(self):
        from psynet.perf_test import wait_for_async_processes

        waiting = wait_for_async_processes(
            timeout_s=_ASYNC_DRAIN_TIMEOUT_S, finished=True
        )
        if waiting:
            raise RuntimeError(
                f"{waiting:,} async processes had not finished after "
                f"{_ASYNC_DRAIN_TIMEOUT_S // 60} minutes, so no snapshot was "
                "taken: their jobs would be lost at each reset. Check the "
                "experiment's async processes in the server log."
            )

    def _take_snapshot(self):
        import psycopg2
        from psycopg2 import sql

        name = self._keep_as
        if name is None:
            stamp = f"_snapshot_{datetime.datetime.now():%Y%m%d%H%M%S}"
            name = self.database[: _MAX_NAME_LENGTH - len(stamp)] + stamp
        try:
            with self._connect() as cursor:
                self._check_disk_space(cursor, self.database)
                _swap_in_copy(cursor, name, self.database)
                if self._description and self._keep_as is not None:
                    cursor.execute(
                        sql.SQL("COMMENT ON DATABASE {} IS %s").format(
                            sql.Identifier(name)
                        ),
                        (self._description,),
                    )
        except psycopg2.Error as e:
            if e.pgcode != _INSUFFICIENT_PRIVILEGE:
                raise
            logger.warning(
                warning(
                    f"The PostgreSQL role may not create databases ({e.pgerror}), "
                    "so the snapshot is a pg_dump archive instead. Resets take "
                    "longer: each one rewrites every table and rebuilds its "
                    "indexes."
                )
            )
            name = self._dump(name)
        self.snapshot, self._owns_snapshot = name, self._keep_as is None
        if self._keep_as is not None:
            logger.info(
                f"Kept the pre-fill snapshot {name}; later runs with the same "
                "experiment code and pre-fill settings start from it."
            )
            self._log_other_snapshots()

    def _log_other_snapshots(self):
        """List the other kept pre-fill snapshots, which take disk space until dropped."""
        others = [
            f"{other} ({size / 1e6:,.0f} MB)"
            for other, size, _ in list_snapshots(
                self.database_url, self._snapshot_directory
            )
            if _snapshot_stem(other) != self._keep_as
        ]
        if others:
            logger.info(
                f"Other pre-fill snapshots: {', '.join(others)}. Drop those you "
                "no longer need with 'psynet performance-test snapshots --drop NAME'."
            )

    def _dump(self, name):
        """Write a ``pg_dump`` archive of the database; return its path."""
        self._snapshot_directory.mkdir(parents=True, exist_ok=True)
        with self._connect() as cursor:
            self._check_disk_space(cursor, self.database, self._snapshot_directory)
        archive = self._snapshot_directory / f"{name}.dump"
        partial = archive.with_suffix(".partial")
        _run_postgres_tool(
            "pg_dump", self.database_url, "--format=custom", f"--file={partial}"
        )
        os.replace(partial, archive)
        return str(archive)

    def _check_disk_space(self, cursor, source, directory=None):
        """Raise unless twice the size of database ``source`` is free where its copy goes.

        The copy goes in PostgreSQL's data directory, or in ``directory`` for
        a ``pg_dump`` archive. If the data directory's free space can't be
        read, for example without permission to read the server's settings
        or for a PostgreSQL in a container, it only warns, once.
        """
        import psycopg2

        cursor.execute("SELECT pg_database_size(%s)", (source,))
        needed = 2 * cursor.fetchone()[0]
        try:
            if directory is None:
                cursor.execute("SHOW data_directory")
                directory = cursor.fetchone()[0]
                if not os.path.isfile(os.path.join(directory, "PG_VERSION")):
                    raise FileNotFoundError(
                        f"its data directory {directory} isn't on this computer"
                    )
            free = shutil.disk_usage(directory).free
        except (psycopg2.Error, OSError) as e:
            if not self._disk_space_unknown:
                self._disk_space_unknown = True
                logger.warning(
                    warning(
                        f"Could not check PostgreSQL's free disk space ({str(e).strip()}); "
                        f"copying {source} needs about {_size(needed)}."
                    )
                )
            return
        if free >= needed:
            return
        cached = sum(
            size
            for _, size, _ in list_snapshots(
                self.database_url, self._snapshot_directory
            )
        )
        raise RuntimeError(
            f"Copying {source} needs about {_size(needed)} of free disk space "
            f"(PsyNet asks for twice the database's size), but {directory} has "
            f"only {_size(free)} free. "
            f"Pre-fill snapshots use {_size(cached)}; drop those you no longer "
            "need with 'psynet performance-test snapshots --drop NAME'."
        )

    def _restore(self):
        if not self.snapshot.endswith(".dump"):
            with self._connect() as cursor:
                self._check_disk_space(cursor, self.snapshot)
                _swap_in_copy(cursor, self.database, self.snapshot)
            return
        with self._connect() as cursor:
            self._check_disk_space(cursor, self.database)
            terminate_connections(cursor, self.database)
        _run_postgres_tool(
            "pg_restore",
            self.database_url,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--single-transaction",
            self.snapshot,
        )

    def _count_rows(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        from psynet.perf_test import _database_rows

        engine = create_engine(self.database_url, poolclass=NullPool)
        try:
            with engine.connect() as connection:
                return _database_rows(connection)
        finally:
            engine.dispose()

    @staticmethod
    def _clear_job_queues():
        """Delete the RQ queues, jobs and worker registrations from Redis."""
        from dallinger.db import redis_conn

        keys = list(redis_conn.scan_iter("rq:*", count=1000))
        for i in range(0, len(keys), 1000):
            redis_conn.delete(*keys[i : i + 1000])


def _swap_in_copy(cursor, target, template):
    """Replace database ``target``, if it exists, with a copy of ``template``.

    The copy is complete before ``target`` is dropped. If renaming the copy
    fails after that, :func:`_recover_database` can finish the swap.
    """
    copy = replacement_name(target)
    # A copy left without its target is the only copy, so it becomes the target.
    _recover_database(cursor, target)
    _run_when_unused(
        cursor, template, _statement("CREATE DATABASE {} TEMPLATE {}", copy, template)
    )
    _run_when_unused(cursor, target, _statement("DROP DATABASE IF EXISTS {}", target))
    _run_when_unused(
        cursor, copy, _statement("ALTER DATABASE {} RENAME TO {}", copy, target)
    )


def _recover_database(cursor, database):
    """Finish an interrupted :func:`_swap_in_copy`; return whether ``database`` exists.

    A leftover copy is always complete, because ``CREATE DATABASE`` either
    finishes or leaves nothing, so it replaces ``database``.
    """
    copy = replacement_name(database)
    if not _database_exists(cursor, copy):
        return _database_exists(cursor, database)
    _run_when_unused(
        cursor, database, _statement("DROP DATABASE IF EXISTS {}", database)
    )
    _run_when_unused(
        cursor, copy, _statement("ALTER DATABASE {} RENAME TO {}", copy, database)
    )
    logger.warning(warning(f"Finished replacing {database} with {copy}."))
    return True


def _statement(template, *names):
    from psycopg2 import sql

    return sql.SQL(template).format(*(sql.Identifier(name) for name in names))


def _run_when_unused(cursor, database, statement):
    """Run ``statement`` after terminating the client connections to ``database``.

    Retries if a client connects again in between, or autovacuum briefly
    holds the database.
    """
    import psycopg2

    for attempt in range(_IN_USE_ATTEMPTS):
        terminate_connections(cursor, database)
        try:
            cursor.execute(statement)
            return
        except psycopg2.Error as e:
            if e.pgcode != _OBJECT_IN_USE or attempt == _IN_USE_ATTEMPTS - 1:
                raise
        time.sleep(1)


@contextmanager
def _maintenance_cursor(database_url):
    """Yield an autocommit cursor on the ``postgres`` database, or ``template1``.

    ``CREATE DATABASE`` and ``DROP DATABASE`` can't run inside a transaction
    or on the database they copy or drop.
    """
    import psycopg2

    parts = urlsplit(database_url)
    try:
        connection = psycopg2.connect(urlunsplit(parts._replace(path="/postgres")))
    except psycopg2.OperationalError:
        connection = psycopg2.connect(urlunsplit(parts._replace(path="/template1")))
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            yield cursor
    finally:
        connection.close()


def _size(n_bytes):
    return f"{n_bytes / 1e9:,.1f} GB" if n_bytes >= 1e9 else f"{n_bytes / 1e6:,.0f} MB"


def _database_exists(cursor, name):
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    return cursor.fetchone() is not None


def _snapshot_stem(snapshot):
    return Path(snapshot).stem if snapshot.endswith(".dump") else snapshot


def _run_postgres_tool(tool, database_url, *args):
    """Run a PostgreSQL client program such as ``pg_dump`` on ``database_url``.

    The password goes in the environment rather than on the command line,
    where other users could read it.
    """
    from sqlalchemy.engine import make_url

    if shutil.which(tool) is None:
        raise RuntimeError(
            f"{tool} is needed to reset the database without permission to "
            "create databases, but it is not installed."
        )
    url = make_url(database_url)
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    dbname = url.set(drivername="postgresql", password=None)
    result = subprocess.run(
        [tool, f"--dbname={dbname.render_as_string()}", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{tool} failed: {result.stderr.strip()}")
