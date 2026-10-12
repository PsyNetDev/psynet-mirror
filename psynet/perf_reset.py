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
- A reset never leaves the experiment without a database: the copy is
  complete before the old database is dropped, and a snapshot is only
  dropped after a successful reset.
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

from psynet.isolated_environment import drop_database, terminate_connections
from psynet.log import warning

logger = logging.getLogger(__name__)

SNAPSHOT_DIRECTORY = Path(".deploy") / "performance_snapshots"
# Async processes left from pre-filling would never run after a reset,
# because the reset deletes their RQ jobs.
_ASYNC_DRAIN_TIMEOUT_S = 3600
_IN_USE_ATTEMPTS = 5
_INSUFFICIENT_PRIVILEGE = "42501"
_OBJECT_IN_USE = "55006"
_MAX_NAME_LENGTH = 63
_PREFILL_NAME = re.compile(r"psynet_prefill_(?P<code>[0-9a-f]{12})_n\d+_k\d+")
_SYSTEM_DATABASES = {"postgres", "template0", "template1"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def check_resettable_database(database_url):
    """Return ``"<database> on <host>"``, or raise if ``--reset-database`` must not drop it.

    Raises
    ------
    ValueError
        If the database is a PostgreSQL system database or isn't on this
        computer, for example a shared one with ``PSYNET_TEST_ENVIRONMENT=shared``.
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
    """Return a short hash of the experiment's authored files and the PsyNet version.

    The files are those that a deployment would copy, without the ones Git
    ignores, such as generated boilerplate.
    """
    import psynet
    from psynet.deployment_info import authored_deployment_files

    files = authored_deployment_files()
    if files is None:
        raise ValueError(
            "Caching pre-fill snapshots needs the experiment's deploy.toml."
        )
    digest = hashlib.sha256(psynet.__version__.encode())
    for destination, source in files:
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
        self._database_complete = True

    def __call__(self):
        """Take or restore the snapshot, with the server stopped meanwhile."""
        from psynet.db import release_local_database_connections

        taking = self.snapshot is None
        if taking:
            if self._prefill is not None:
                self._prefill()
            self._wait_for_async_processes()
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
        finally:
            self._start_server()
        if self.snapshot_rows is None:
            self.snapshot_rows = self._count_rows()
            rows = ", ".join(f"{t} {n:,}" for t, n in self.snapshot_rows.items())
            logger.info(f"Snapshot {self.snapshot}: {rows} rows.")

    def close(self):
        """Drop a snapshot taken here unless it is kept, once the database is complete."""
        import psycopg2

        if not self._owns_snapshot:
            return
        kept = (
            f"Kept the snapshot {self.snapshot}, because the last reset failed "
            f"and {self.database} may be incomplete."
        )
        if not self._database_complete:
            logger.warning(warning(kept))
            return
        if self.snapshot.endswith(".dump"):
            os.remove(self.snapshot)
            return
        try:
            with self._connect() as cursor:
                if not _database_exists(cursor, self.database):
                    logger.warning(warning(kept))
                    return
                drop_database(cursor, self.snapshot)
        except psycopg2.Error as e:
            logger.warning(
                warning(
                    f"Could not drop the snapshot database {self.snapshot} ({e}). "
                    f"Drop it with 'dropdb {self.snapshot}'."
                )
            )

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
                if self._keep_as is not None:
                    drop_database(cursor, name)
                self._while_in_use(
                    cursor,
                    self.database,
                    sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                        sql.Identifier(name), sql.Identifier(self.database)
                    ),
                )
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

    def _dump(self, name):
        """Write a ``pg_dump`` archive of the database; return its path."""
        self._snapshot_directory.mkdir(parents=True, exist_ok=True)
        archive = self._snapshot_directory / f"{name}.dump"
        partial = archive.with_suffix(".partial")
        _run_postgres_tool(
            "pg_dump", self.database_url, "--format=custom", f"--file={partial}"
        )
        os.replace(partial, archive)
        return str(archive)

    def _restore(self):
        from psycopg2 import sql

        self._database_complete = False
        if self.snapshot.endswith(".dump"):
            with self._connect() as cursor:
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
        else:
            copy = self.database[: _MAX_NAME_LENGTH - 5] + "__new"
            with self._connect() as cursor:
                drop_database(cursor, copy)
                self._while_in_use(
                    cursor,
                    self.snapshot,
                    sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                        sql.Identifier(copy), sql.Identifier(self.snapshot)
                    ),
                )
                self._while_in_use(
                    cursor,
                    self.database,
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.database)),
                )
                cursor.execute(
                    sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                        sql.Identifier(copy), sql.Identifier(self.database)
                    )
                )
        self._database_complete = True

    def _while_in_use(self, cursor, database, statement):
        """Run ``statement`` after terminating the connections to ``database``.

        Retries if a client connects again in between.
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
