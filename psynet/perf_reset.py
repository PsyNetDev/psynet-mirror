"""Start every performance test from the same database.

``psynet performance-test local --reset-database`` resets the experiment's
database before each test of a suite, so that the tests of ``--n-bots auto``
compare load rather than amounts of data. :class:`DatabaseReset` is the
suite's ``before_test`` hook (see :class:`psynet.perf_test.PerformanceSuite`).

Before the first test it takes a snapshot of the database with ``CREATE
DATABASE ... TEMPLATE``, a file-level copy that keeps sequences, indexes and
table bloat; before each later test it recreates the database from that
snapshot. PostgreSQL only copies a database that nobody is connected to, so
the hook stops the experiment server, terminates the connections that remain
(for example those of bot processes), and starts the server again afterwards.
Restarting also empties the server's in-memory caches, some of which hold row
IDs. The hook also deletes the RQ job keys from Redis, because jobs refer to
rows by ID, but keeps the other keys, such as the launch flags without which
the server would launch the experiment again.

Design constraints:

- Only the experiment's own database and the snapshot taken here are ever
  dropped. A snapshot passed as ``from_snapshot`` is only read.
- If the PostgreSQL role may not create databases, the snapshot is a
  ``pg_dump`` archive that each reset restores with ``pg_restore --clean``.
  That is slower, and leaves the tables freshly packed.
- Files that tests add to the asset storage remain after a reset; only the
  rows that refer to them go.

The class doesn't know how the server runs: callers pass functions that stop
and start it, so that a remote deployment can reuse it with its own functions
and, by overriding :meth:`DatabaseReset._connect`, its own database access.
"""

import datetime
import logging
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

from psynet.log import warning

logger = logging.getLogger(__name__)

# Async processes left from pre-filling would never run after a reset,
# because the reset deletes their RQ jobs.
_ASYNC_DRAIN_TIMEOUT_S = 3600
_IN_USE_ATTEMPTS = 5
_INSUFFICIENT_PRIVILEGE = "42501"
_OBJECT_IN_USE = "55006"
_MAX_NAME_LENGTH = 63


class DatabaseReset:
    """Reset the experiment database to a snapshot before each call.

    The first call adds any pre-fill data, waits for async processes to
    finish, and takes the snapshot; with ``from_snapshot`` it restores that
    snapshot instead. Every later call restores the snapshot. Each call
    stops the server first and starts it again at the end.

    Parameters
    ----------
    stop_server, start_server : callable
        Stop the experiment server's processes; start them again and wait
        until the server answers.
    prefill : callable, optional
        Called with the server running before the snapshot is taken, to add
        data (see :func:`psynet.perf_test.prefill_database`).
    from_snapshot : str, optional
        A snapshot that an earlier run kept: a database name, or the path of
        a ``pg_dump`` archive.
    keep_snapshot : bool
        Keep the snapshot at :meth:`close` rather than dropping it.
    dump_directory : str, optional
        Where to write a ``pg_dump`` archive if the role may not create
        databases. Defaults to the current directory.
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
        keep_snapshot=False,
        dump_directory=None,
        database_url=None,
    ):
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
        self._keep_snapshot = keep_snapshot
        self._owns_snapshot = False
        self._dump_directory = dump_directory or os.getcwd()
        if from_snapshot is not None:
            self._check_snapshot_exists()

    def __call__(self):
        """Take or restore the snapshot, with the server stopped meanwhile."""
        from psynet.db import release_local_database_connections
        from psynet.perf_test import _database_rows, wait_for_async_processes

        taking = self.snapshot is None
        if taking:
            if self._prefill is not None:
                self._prefill()
            if wait_for_async_processes(
                timeout_s=_ASYNC_DRAIN_TIMEOUT_S, finished=True
            ):
                logger.warning(
                    warning(
                        "Some async processes have not finished; they will "
                        "never run in the tests, because each reset deletes "
                        "their jobs."
                    )
                )
        logger.info("")
        logger.info(
            "Taking a snapshot of the database..."
            if taking
            else f"Resetting the database to {self.snapshot}..."
        )
        self._stop_server()
        release_local_database_connections()
        if taking:
            self._take_snapshot()
        else:
            self._restore()
        self._clear_job_queues()
        self._start_server()
        if self.snapshot_rows is None:
            self.snapshot_rows = _database_rows()
            rows = ", ".join(f"{t} {n:,}" for t, n in self.snapshot_rows.items())
            logger.info(f"Snapshot {self.snapshot}: {rows} rows.")

    def close(self):
        """Drop the snapshot taken here, unless it is to be kept."""
        if not self._owns_snapshot:
            return
        if self._keep_snapshot:
            logger.info(
                f"Kept the database snapshot {self.snapshot}; start later "
                f"runs from it with --from-snapshot {self.snapshot}."
            )
            return
        if os.path.isfile(self.snapshot):
            os.remove(self.snapshot)
            return
        import psycopg2

        try:
            with self._connect() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS {_quote(self.snapshot)}")
        except psycopg2.Error as e:
            logger.warning(
                warning(
                    f"Could not drop the snapshot database {self.snapshot} ({e}). "
                    f"Drop it with 'dropdb {self.snapshot}'."
                )
            )

    @contextmanager
    def _connect(self):
        """Yield a cursor on the server's ``postgres`` database, outside transactions.

        ``CREATE DATABASE`` and ``DROP DATABASE`` can't run inside a
        transaction or on the database they copy or drop.
        """
        import psycopg2

        parts = urlsplit(self.database_url)
        connection = psycopg2.connect(urlunsplit(parts._replace(path="/postgres")))
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                yield cursor
        finally:
            connection.close()

    def _check_snapshot_exists(self):
        if os.path.isfile(self.snapshot):
            return
        if self.snapshot == self.database:
            raise ValueError("The snapshot can't be the experiment database itself.")
        with self._connect() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (self.snapshot,)
            )
            if cursor.fetchone() is None:
                raise ValueError(
                    f"No snapshot database or pg_dump archive named {self.snapshot}."
                )

    def _take_snapshot(self):
        import psycopg2

        stamp = f"_snapshot_{datetime.datetime.now():%Y%m%d%H%M%S}"
        name = self.database[: _MAX_NAME_LENGTH - len(stamp)] + stamp
        try:
            with self._connect() as cursor:
                self._while_in_use(
                    cursor,
                    f"CREATE DATABASE {_quote(name)} TEMPLATE {_quote(self.database)}",
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
            name = os.path.join(self._dump_directory, f"{name}.dump")
            _run_postgres_tool(
                "pg_dump", "--format=custom", f"--file={name}", self.database_url
            )
        self.snapshot, self._owns_snapshot = name, True

    def _restore(self):
        if os.path.isfile(self.snapshot):
            with self._connect() as cursor:
                self._terminate_connections(cursor)
            _run_postgres_tool(
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                f"--dbname={self.database_url}",
                self.snapshot,
            )
            return
        with self._connect() as cursor:
            self._while_in_use(
                cursor, f"DROP DATABASE IF EXISTS {_quote(self.database)}"
            )
            cursor.execute(
                f"CREATE DATABASE {_quote(self.database)} "
                f"TEMPLATE {_quote(self.snapshot)}"
            )

    def _while_in_use(self, cursor, statement):
        """Run ``statement`` after terminating the experiment database's connections.

        Retries if a client connects again in between.
        """
        import psycopg2

        for attempt in range(_IN_USE_ATTEMPTS):
            self._terminate_connections(cursor)
            try:
                cursor.execute(statement)
                return
            except psycopg2.Error as e:
                if e.pgcode != _OBJECT_IN_USE or attempt == _IN_USE_ATTEMPTS - 1:
                    raise
            time.sleep(1)

    def _terminate_connections(self, cursor):
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (self.database,),
        )

    @staticmethod
    def _clear_job_queues():
        """Delete the RQ queues, jobs and worker registrations from Redis."""
        from dallinger.db import redis_conn

        keys = list(redis_conn.scan_iter("rq:*", count=1000))
        for i in range(0, len(keys), 1000):
            redis_conn.delete(*keys[i : i + 1000])


def _quote(name):
    """Quote a PostgreSQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _run_postgres_tool(tool, *args):
    """Run a PostgreSQL client program such as ``pg_dump``.

    ``pg_restore`` carries on past errors, for example settings that an older
    server doesn't know, and reports them at the end, so its errors are
    warnings; ``pg_dump`` errors raise.
    """
    if shutil.which(tool) is None:
        raise RuntimeError(
            f"{tool} is needed to reset the database without permission to "
            "create databases, but it is not installed."
        )
    result = subprocess.run([tool, *args], capture_output=True, text=True)
    if result.returncode == 0:
        return
    if tool != "pg_restore":
        raise RuntimeError(f"{tool} failed: {result.stderr.strip()}")
    logger.warning(warning(f"pg_restore reported errors: {result.stderr.strip()}"))
