"""Start every performance test from the same database.

``psynet performance-test local --reset-database`` resets the experiment's
database before each test of a suite, so that the tests of ``--n-bots auto``
compare load rather than amounts of data. :class:`DatabaseReset` is the
suite's ``before_test`` hook (see :class:`psynet.perf_test.PerformanceSuite`).

Before the first test it takes a snapshot of the database with ``CREATE
DATABASE ... TEMPLATE``, a file-level copy that keeps sequences, indexes and
table bloat; before each later test it drops the experiment database and
creates it again from the snapshot. PostgreSQL only copies or drops a
database that nobody is connected to, so the hook stops the experiment
server, terminates the connections that remain, and starts the server again
afterwards. Restarting also empties the server's in-memory caches, some of
which hold row IDs. The hook also deletes the RQ job keys from Redis, because
jobs refer to rows by ID, but keeps the other keys, such as the launch flags
without which the server would launch the experiment again.

With ``--prefill-participants``, bots first add data, and the snapshot is
kept as a pre-fill cache under a name made from the experiment code, the
PsyNet version and the number of pre-fill participants (see
:func:`prefill_snapshot_name`), so that a later run with the same code and
number starts from it instead of pre-filling again. To pre-fill again, drop
it with ``psynet performance-test snapshots --drop NAME``.

Design constraints:

- Snapshots are separate databases that are created once and never
  changed; only the experiment database is replaced. A kept snapshot is
  only dropped on request.
- Only the experiment database and snapshots that this module names are
  ever dropped, and only on this computer's PostgreSQL server. The
  experiment database must be the disposable one that the isolated test
  environment created for this session (see
  :func:`check_resettable_database`), never one that a researcher debugs
  with.
- A pre-fill can take hours, so if it finishes but its snapshot isn't
  taken, for example after an interrupt, :meth:`DatabaseReset.close` takes
  it.
- The PostgreSQL role must be allowed to create databases, as the isolated
  test environment already requires.
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
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.engine import make_url

from psynet.isolated_environment import (
    DATABASE_ENV_VAR,
    SHARED,
    drop_database,
    terminate_connections,
)
from psynet.log import warning

logger = logging.getLogger(__name__)

# Async processes left from pre-filling would never run after a reset,
# because the reset deletes their RQ jobs.
_ASYNC_DRAIN_TIMEOUT_S = 3600
_IN_USE_ATTEMPTS = 10
_INSUFFICIENT_PRIVILEGE = "42501"
_OBJECT_IN_USE = "55006"
_MAX_NAME_LENGTH = 63
_PREFILL_NAME = re.compile(r"psynet_prefill_(?P<code>[0-9a-f]{12})_n\d+")
_SESSION_DATABASE = re.compile(r".+_test_\d+")
_SYSTEM_DATABASES = {"postgres", "template0", "template1"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SETTINGS_FILES = ("config.txt", "requirements.txt", "constraints.txt")


def check_local_database(database_url):
    """Return ``"<database> on <host>"``, or raise unless it is on this computer.

    Raises
    ------
    ValueError
        If the database is a PostgreSQL system database or isn't on this
        computer's PostgreSQL server.
    """
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


def check_resettable_database(database_url, environ=None):
    """Return ``"<database> on <host>"``, or raise if ``--reset-database`` must not drop it.

    Resetting drops the database, so it is only allowed for the database that
    the isolated test environment created for this session, which it names
    in :data:`psynet.isolated_environment.DATABASE_ENV_VAR` and drops when the
    session ends. Without isolation, for example with ``CI`` or
    ``PSYNET_TEST_ENVIRONMENT=shared`` set, the database may be the one you
    debug with, such as ``dallinger``.

    Parameters
    ----------
    database_url : str
        The experiment database.
    environ : dict, optional
        The environment variables. Defaults to ``os.environ``.

    Raises
    ------
    ValueError
        If the database isn't the isolated test session's own, is a
        PostgreSQL system database, or isn't on this computer.
    """
    environ = os.environ if environ is None else environ
    description = check_local_database(database_url)
    database = make_url(database_url).database
    if database != environ.get(DATABASE_ENV_VAR) or not _SESSION_DATABASE.fullmatch(
        database
    ):
        raise ValueError(
            f"Refusing to reset the database {database}: resetting drops and "
            "recreates the database, so it only works in the database that the "
            "isolated test environment creates for 'psynet performance-test "
            "local'. That environment is skipped when CI or "
            f"PSYNET_TEST_ENVIRONMENT={SHARED} is set; unset them and run the "
            "command again."
        )
    return description


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


def prefill_snapshot_name(code_key, n_participants):
    """Return the name of the pre-fill snapshot for this code and number of participants."""
    return f"psynet_prefill_{code_key}_n{n_participants}"


def snapshot_code_key(snapshot):
    """Return the code key in a pre-fill snapshot's name, or ``None``."""
    match = _PREFILL_NAME.fullmatch(snapshot)
    return match["code"] if match else None


def find_snapshot(name, database_url):
    """Return snapshot database ``name`` if it exists, otherwise ``None``."""
    with _maintenance_cursor(database_url) as cursor:
        return name if _database_exists(cursor, name) else None


def check_snapshot(snapshot, database_url):
    """Raise ``ValueError`` unless ``snapshot`` is a pre-fill snapshot that exists."""
    if snapshot_code_key(snapshot) is None:
        raise ValueError(
            f"{snapshot} is not a pre-fill snapshot; list them with "
            "'psynet performance-test snapshots'."
        )
    with _maintenance_cursor(database_url) as cursor:
        if not _database_exists(cursor, snapshot):
            raise ValueError(f"No snapshot database {snapshot}.")


def list_snapshots(database_url):
    """Return ``(name, size_bytes, description)`` for each pre-fill snapshot.

    The snapshots are databases on the server, which all experiments share.
    """
    with _maintenance_cursor(database_url) as cursor:
        cursor.execute(
            "SELECT datname, pg_database_size(oid), "
            "shobj_description(oid, 'pg_database') FROM pg_database "
            "WHERE datname LIKE 'psynet\\_prefill\\_%' ORDER BY datname"
        )
        return [row for row in cursor.fetchall() if snapshot_code_key(row[0])]


def drop_snapshot(snapshot, database_url):
    """Drop a pre-fill snapshot database."""
    if snapshot_code_key(snapshot) is None:
        raise ValueError(f"{snapshot} is not a pre-fill snapshot.")
    with _maintenance_cursor(database_url) as cursor:
        drop_database(cursor, snapshot)


class DatabaseReset:
    """Reset the experiment database to a snapshot before each call.

    The first call adds any pre-fill data, waits for async processes to
    finish, and takes the snapshot; with ``from_snapshot`` it restores that
    snapshot instead. Every later call restores the snapshot. Each call
    stops the server first and starts it again afterwards.

    Parameters
    ----------
    stop_server, start_server : callable
        Stop the experiment server's processes; start them again and wait
        until the server answers.
    prefill : callable, optional
        Called with the server running before the snapshot is taken, to add
        data (see :func:`psynet.perf_test.prefill_database`).
    from_snapshot : str, optional
        The name of a snapshot database to start from. It is only read.
    keep_as : str, optional
        Take the snapshot under this pre-fill snapshot name (see
        :func:`prefill_snapshot_name`), which must not exist yet, and keep
        it. Otherwise the snapshot is dropped at :meth:`close`.
    description : str, optional
        Stored as the comment of a kept snapshot database.
    database_url : str, optional
        The experiment database. Defaults to Dallinger's.

    Raises
    ------
    ValueError
        If the database may not be reset (see :func:`check_resettable_database`).
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
        database_url=None,
    ):
        if keep_as is not None and snapshot_code_key(keep_as) is None:
            raise ValueError(f"{keep_as} is not a pre-fill snapshot name.")
        if database_url is None:
            from dallinger import db

            database_url = db.engine.url.render_as_string(hide_password=False)
        check_resettable_database(database_url)
        self.database_url = database_url
        self.database = make_url(database_url).database
        self.snapshot = from_snapshot
        # Rows in each growing table of the snapshot, once restored or taken.
        self.snapshot_rows = None
        self._stop_server = stop_server
        self._start_server = start_server
        self._prefill = prefill
        self._keep_as = keep_as
        self._description = description
        self._drop_snapshot_on_close = False
        self._disk_space_unknown = False
        # Whether the pre-fill for ``keep_as`` and its async processes finished.
        self._prefilled = False

    def __call__(self):
        """Take or restore the snapshot, with the server stopped meanwhile.

        The server starts again afterwards. If taking or restoring the
        snapshot fails, the server stays stopped and the error propagates;
        the caller then shuts the server down.
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
        release_local_database_connections()
        if taking:
            self._take_snapshot()
        else:
            self._restore()
        self._clear_job_queues()
        self._start_server()
        if self.snapshot_rows is None:
            self.snapshot_rows = self._count_rows()
            rows = ", ".join(f"{t} {n:,}" for t, n in self.snapshot_rows.items())
            logger.info(f"Snapshot {self.snapshot}: {rows} rows.")

    def close(self):
        """Keep a finished pre-fill whose snapshot failed, then drop a snapshot taken here.

        Errors are only logged, so that a test's own error is the one that
        propagates.
        """
        import psycopg2

        try:
            if self._prefilled and self.snapshot is None:
                self._take_snapshot()
            if self._drop_snapshot_on_close:
                with self._connect() as cursor:
                    drop_database(cursor, self.snapshot)
        except (psycopg2.Error, RuntimeError) as e:
            advice = (
                "The pre-filled data was not kept."
                if self.snapshot is None
                else f"Drop the snapshot with 'dropdb {self.snapshot}'."
            )
            logger.warning(
                warning(f"Could not finish resetting the database ({e}). {advice}")
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
        from psycopg2 import sql

        name = self._keep_as
        if name is None:
            stamp = f"_snapshot_{datetime.datetime.now():%Y%m%d%H%M%S}"
            name = self.database[: _MAX_NAME_LENGTH - len(stamp)] + stamp
        with self._connect() as cursor:
            self._check_disk_space(cursor, self.database)
            _create_from_template(cursor, name, self.database)
            self.snapshot, self._drop_snapshot_on_close = name, self._keep_as is None
            if self._description and self._keep_as is not None:
                cursor.execute(
                    sql.SQL("COMMENT ON DATABASE {} IS %s").format(
                        sql.Identifier(name)
                    ),
                    (self._description,),
                )
        if self._keep_as is not None:
            logger.info(
                f"Kept the pre-fill snapshot {name}; later runs with the same "
                "experiment code and number of pre-fill participants start from it."
            )
            self._log_other_snapshots()

    def _log_other_snapshots(self):
        """List the other kept pre-fill snapshots, which take disk space until dropped."""
        others = [
            f"{other} ({size / 1e6:,.0f} MB)"
            for other, size, _ in list_snapshots(self.database_url)
            if other != self._keep_as
        ]
        if others:
            logger.info(
                f"Other pre-fill snapshots: {', '.join(others)}. Drop those you "
                "no longer need with 'psynet performance-test snapshots --drop NAME'."
            )

    def _check_disk_space(self, cursor, source):
        """Raise unless PostgreSQL's data directory has twice the size of database ``source`` free.

        If the data directory's free space can't be read, for example without
        permission to read the server's settings or for a PostgreSQL in a
        container, it only warns, once.
        """
        import psycopg2

        cursor.execute("SELECT pg_database_size(%s)", (source,))
        needed = 2 * cursor.fetchone()[0]
        try:
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
        cached = sum(size for _, size, _ in list_snapshots(self.database_url))
        raise RuntimeError(
            f"Copying {source} needs about {_size(needed)} of free disk space "
            f"(PsyNet asks for twice the database's size), but {directory} has "
            f"only {_size(free)} free. "
            f"Pre-fill snapshots use {_size(cached)}; drop those you no longer "
            "need with 'psynet performance-test snapshots --drop NAME'."
        )

    def _restore(self):
        with self._connect() as cursor:
            self._check_disk_space(cursor, self.snapshot)
            _run_when_unused(
                cursor,
                self.database,
                _statement("DROP DATABASE IF EXISTS {}", self.database),
            )
            _create_from_template(cursor, self.database, self.snapshot)

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


def _create_from_template(cursor, name, template):
    """Create database ``name`` as a copy of database ``template``.

    Raises
    ------
    RuntimeError
        If the PostgreSQL role may not create databases.
    """
    import psycopg2

    try:
        _run_when_unused(
            cursor,
            template,
            _statement("CREATE DATABASE {} TEMPLATE {}", name, template),
        )
    except psycopg2.Error as e:
        if e.pgcode != _INSUFFICIENT_PRIVILEGE:
            raise
        raise RuntimeError(
            "Resetting the database copies it with CREATE DATABASE, which the "
            f"PostgreSQL role may not do ({str(e).strip()}). Use a role that "
            "may create databases, as the isolated test environment does, for "
            "example by running 'ALTER ROLE <role> CREATEDB' as a superuser."
        ) from e


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
