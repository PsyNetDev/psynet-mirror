"""Run local tests in their own database, Redis server, port and develop folder.

Why this exists
---------------
By default ``psynet debug local`` and PsyNet's tests share one local
environment: the ``dallinger`` PostgreSQL database, the Redis server on port
6379, web port 5000 and ``/tmp/dallinger_develop``. Tests need a clean
environment, so they reset the database and Redis and stop local servers that
use the same database. Before this module, running tests therefore wiped and
stopped any experiment you were debugging.

An isolated environment gives the test session:

- a free web port (at least 100 above Dallinger's ``base_port``), claimed
  with a lock file so that concurrent sessions choose different ports;
- the ``<database>_test_<port>`` database next to ``DATABASE_URL``, created
  afresh when the session starts and dropped when it ends;
- a private ``redis-server`` on the shared Redis port plus the same offset,
  stopped when the session ends (Redis delivers live notifications to every
  database on a server, so a database number on the shared server, emptied
  when the session ends, is only a fallback);
- its own ``dallinger_develop_directory``.

PsyNet's process cleanup already only targets processes that use the current
``DATABASE_URL`` (see ``psynet.command_line.uses_current_database``), so once
the URLs differ the tests leave a running ``psynet debug local`` alone.

``psynet debug local --isolated`` gives a debug server the same kind of
environment, so that it runs next to other servers and test sessions; like a
test session's, its database and Redis are removed when it stops. Remote
launches (``psynet debug ssh``, ``psynet deploy heroku`` and so on) run
``psynet prepare`` in one too, so building the starting database they ship to
the server leaves the local database and Redis alone.

Design constraints
------------------
Dallinger connects to PostgreSQL and Redis when ``dallinger.db`` is first
imported, so the environment variables must change before that import. This
module therefore imports nothing from Dallinger. It is used in two places:

- :mod:`psynet.pytest_environment`, an early pytest plugin that PsyNet's
  pytest configuration and the experiment ``pytest.ini`` template load with
  ``-p``. Plugins named with ``-p`` are imported before auto-loaded plugins
  such as ``pytest_dallinger`` and ``pytest_psynet``.
- ``psynet test local``, ``psynet performance-test local`` and
  ``psynet debug local --isolated``, which have already imported Dallinger
  by the time they run, and so re-run themselves in a child process inside
  the environment. Remote launches likewise run only ``psynet prepare`` in a
  child process.

``PSYNET_TEST_ENVIRONMENT`` may be unset, ``isolated`` (the default) or
``shared`` (opt out); other values are an error, so a typo can't silently turn
isolation off. Sessions do nothing when :data:`READY_ENV_VAR` is set, which
marks the processes a session starts once their environment is chosen, or when
``CI`` is set, because CI machines run no debug server and their test slots
are isolated already.

Isolation separates services, not files: tests still scaffold and remove
generated files in the experiment directory, so a ``psynet debug`` serving the
same directory breaks. Servers and tests therefore share the directory lock
in :mod:`psynet.testing.locks`: tests wait for each other, but refuse to start
while a server holds it.
"""

import fcntl
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

ENV_VAR = "PSYNET_TEST_ENVIRONMENT"
ISOLATED = "isolated"
SHARED = "shared"
#: Set for processes that a test session starts after choosing their environment.
READY_ENV_VAR = "_PSYNET_TEST_ENVIRONMENT_READY"

DEFAULT_DATABASE_URL = "postgresql://dallinger:dallinger@localhost/dallinger"
DEFAULT_REDIS_URL = "redis://localhost:6379"
_DEFAULT_BASE_PORT = 5000
_PORT_OFFSET = 100


def local_base_port(environ=None, directory="."):
    """Return Dallinger's ``base_port`` without importing the experiment.

    Follows Dallinger's precedence: the ``base_port`` environment variable,
    then ``config.txt`` in ``directory``, then ``~/.dallingerconfig``, then
    5000. Like Dallinger, a later section of a file overrides an earlier one.
    A ``base_port`` set in the experiment class's ``config`` dictionary is not
    seen. Files that don't exist or can't be opened are skipped.

    Parameters
    ----------
    environ : mapping, optional
        The environment to read, by default ``os.environ``. Its ``HOME``
        locates ``~/.dallingerconfig``.
    directory : str, optional
        The directory whose ``config.txt`` is read, by default the current
        directory.

    Returns
    -------
    int
        The port.

    Raises
    ------
    ValueError
        If a configuration file can't be parsed or ``base_port`` isn't a number.
    """
    import configparser

    environ = os.environ if environ is None else environ
    if "base_port" in environ:
        return int(environ["base_port"])
    home = environ.get("HOME") or os.path.expanduser("~")
    for path in (
        os.path.join(directory, "config.txt"),
        os.path.join(home, ".dallingerconfig"),
    ):
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(path)
        except (configparser.Error, UnicodeDecodeError) as e:
            raise ValueError(f"Could not read {path}: {e}") from e
        values = [
            parser[s]["base_port"]
            for s in parser.sections()
            if "base_port" in parser[s]
        ]
        if values:
            return int(values[-1])
    return _DEFAULT_BASE_PORT


def should_isolate(environ=None):
    """Return whether a new test session should start an isolated environment.

    Raises
    ------
    ValueError
        If ``PSYNET_TEST_ENVIRONMENT`` is neither unset, ``isolated`` nor ``shared``.
    """
    environ = os.environ if environ is None else environ
    value = environ.get(ENV_VAR, "")
    if value not in ("", ISOLATED, SHARED):
        raise ValueError(
            f"{ENV_VAR} must be {ISOLATED!r} (the default) or {SHARED!r}, not {value!r}."
        )
    return value != SHARED and not _is_configured(environ)


def shared_environment_warning(environ=None):
    """Return a warning for a session that opted out of isolation, or None."""
    environ = os.environ if environ is None else environ
    if environ.get(ENV_VAR) != SHARED or _is_configured(environ):
        return None
    return (
        f"{ENV_VAR}={SHARED}: these tests use the local database, Redis and port, "
        "so they reset them and stop any local debug server that uses them."
    )


def _in_ci(environ=None):
    """Return whether ``CI`` is set, so the services are the CI job's own."""
    environ = os.environ if environ is None else environ
    return environ.get("CI", "").lower() not in ("", "0", "false")


def _is_configured(environ):
    return bool(environ.get(READY_ENV_VAR)) or _in_ci(environ)


#: PostgreSQL's SQLSTATE for ``too_many_connections``.
_TOO_MANY_CONNECTIONS_SQLSTATE = "53300"
_TOO_MANY_CONNECTIONS_TEXTS = (
    "too many clients already",
    "remaining connection slots are reserved",
)


def postgres_connection_limit_message(error):
    """Explain a PostgreSQL "too many connections" error, or return None.

    Parameters
    ----------
    error : BaseException or str
        An exception (for example from psycopg2 or SQLAlchemy) or text such as
        server output.

    Returns
    -------
    str or None
        Advice for the user if ``error`` says that the server has run out of
        connections, otherwise None.
    """
    if getattr(error, "pgcode", None) == _TOO_MANY_CONNECTIONS_SQLSTATE or any(
        text in str(error) for text in _TOO_MANY_CONNECTIONS_TEXTS
    ):
        return (
            "The local PostgreSQL server has run out of connections. Every local "
            "experiment, test session and database shares this server and its "
            "max_connections limit (100 by default). Run fewer bots or test "
            "sessions at once, stop other local experiments, or raise "
            "max_connections in postgresql.conf (psql -c 'SHOW config_file' "
            "shows where it is) and restart PostgreSQL."
        )
    return None


class IsolationError(RuntimeError):
    """Raised when a test session can't get its own database and Redis.

    The message gives the reason and how to opt out (or, if PostgreSQL ran out
    of connections, how to free some), so callers can show ``str(error)`` as
    is; the original exception is the ``__cause__``.
    """

    def __init__(self, reason):
        advice = postgres_connection_limit_message(reason) or (
            f"Set {ENV_VAR}={SHARED} to run them against the local database and "
            "Redis instead, which resets any local debug server."
        )
        super().__init__(
            f"Could not give these tests their own database and Redis ({reason}). "
            f"{advice}"
        )


class IsolatedEnvironment:
    """Environment variables for an isolated test session, plus its Redis server.

    Use :meth:`start` to create one and :meth:`close` (or a ``with`` block) to
    stop its Redis server.
    """

    def __init__(self, env, port_lock=None, redis_process=None):
        self.env = env
        self._port_lock = port_lock
        self._redis_process = redis_process

    @classmethod
    def start(cls, environ=None):
        """Create the test database and start Redis; return the new environment.

        Raises
        ------
        IsolationError
            If ``base_port`` can't be read, no free port is found, PostgreSQL
            can't be reached, the test database can't be created or Redis
            doesn't start; the message
            says how to opt out. Other errors propagate unchanged, because
            opting out would not fix them.
        """
        import psycopg2

        try:
            return cls._start(environ)
        except (OSError, RuntimeError, ValueError, psycopg2.Error) as e:
            raise IsolationError(e) from e

    @classmethod
    def _start(cls, environ):
        environ = dict(os.environ if environ is None else environ)
        database_url = environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        redis_url = environ.get("REDIS_URL", DEFAULT_REDIS_URL)
        private_redis = shutil.which("redis-server") is not None
        shared_base_port = local_base_port(environ)
        shared_redis_port = urlsplit(redis_url).port or 6379

        def redis_port(web_port):
            # Offsetting from the claimed web port keeps concurrent sessions
            # from picking the same Redis port.
            return shared_redis_port + web_port - shared_base_port

        base_port, port_lock = _claim_port(
            shared_base_port + _PORT_OFFSET,
            also_free=redis_port if private_redis else None,
        )
        session_database_url = None
        try:
            session_database_url = create_database(
                database_url, suffix=f"_test_{base_port}"
            )
            env = {
                **environ,
                READY_ENV_VAR: "1",
                "DATABASE_URL": session_database_url,
                "base_port": str(base_port),
                "dallinger_develop_directory": f"/tmp/dallinger_develop_{base_port}",
            }
            if not private_redis:
                slot = (base_port - shared_base_port - _PORT_OFFSET) // 10
                number = _spare_redis_database(redis_url, slot)
                env["REDIS_URL"] = _with_redis_database(redis_url, number)
                print(
                    f"redis-server is not on PATH, so this session uses Redis database "
                    f"{number} on the shared server. Live notifications can still "
                    "reach a local debug server's participants.",
                    file=sys.stderr,
                )
                return cls(env, port_lock)

            process = start_redis_server(redis_port(base_port))
        except BaseException:
            if session_database_url is not None:
                _drop_session_database(session_database_url)
            port_lock.close()
            raise
        env["REDIS_URL"] = f"redis://127.0.0.1:{redis_port(base_port)}"
        return cls(env, port_lock, process)

    def describe(self):
        """Return a one-line summary of where the session's services are."""
        database = urlsplit(self.env["DATABASE_URL"]).path.lstrip("/")
        redis = urlsplit(self.env["REDIS_URL"])
        redis_database = redis.path.lstrip("/") or "0"
        return (
            f"Using database {database}, Redis at {redis.hostname}:"
            f"{redis.port or 6379}/{redis_database}, and port {self.env['base_port']}."
        )

    def close(self):
        """Stop or empty the session's Redis and drop its database."""
        if self._redis_process is not None:
            _stop_process(self._redis_process)
            self._redis_process = None
        elif self._port_lock is not None:
            _flush_redis_database(self.env["REDIS_URL"])
        if self._port_lock is not None:
            # While the port is still claimed, so no new session is using it yet.
            shutil.rmtree(self.env["dallinger_develop_directory"], ignore_errors=True)
            _drop_session_database(self.env["DATABASE_URL"])
            self._port_lock.close()
            self._port_lock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def create_database(database_url, *, suffix):
    """Create an empty ``<database><suffix>`` next to ``database_url``; return its URL.

    A database of that name left by an earlier session is dropped first.
    """
    import psycopg2
    from psycopg2 import sql

    parts = urlsplit(database_url)
    name = f"{parts.path.lstrip('/') or 'dallinger'}{suffix}"
    try:
        connection = psycopg2.connect(database_url)
    except psycopg2.Error as e:
        raise RuntimeError(f"Could not connect to {parts.hostname}: {e}") from e
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            _drop_database(cursor, name)
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        connection.close()
    return urlunsplit(parts._replace(path=f"/{name}"))


def _drop_database(cursor, name):
    """Drop database ``name`` if it exists, after terminating its connections."""
    from psycopg2 import sql

    _terminate_connections(cursor, name)
    cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def _terminate_connections(cursor, name):
    """Terminate the other client connections to database ``name``.

    ``DROP DATABASE ... WITH (FORCE)`` would do this, but needs PostgreSQL 13,
    and ``psynet services ensure`` starts PostgreSQL 12. Autovacuum workers
    are left alone: only a superuser may terminate them, and ``CREATE
    DATABASE`` and ``DROP DATABASE`` stop them anyway.
    """
    cursor.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid() "
        "AND backend_type = 'client backend'",
        (name,),
    )


def _drop_session_database(session_database_url):
    """Drop a session's database, warning instead of raising if that fails."""
    import psycopg2

    parts = urlsplit(session_database_url)
    name = parts.path.lstrip("/")
    shared_url = urlunsplit(parts._replace(path=re.sub(r"_test_\d+$", "", parts.path)))
    try:
        connection = psycopg2.connect(shared_url)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                _drop_database(cursor, name)
        finally:
            connection.close()
    except psycopg2.Error as e:
        print(
            f"Warning: could not drop database {name} ({e}). Drop it with "
            f"'dropdb {name}'.",
            file=sys.stderr,
        )


def _flush_redis_database(redis_url):
    """Empty a spare Redis database, warning instead of raising if that fails."""
    import redis

    try:
        redis.Redis.from_url(redis_url).flushdb()
    except redis.RedisError as e:
        print(
            f"Warning: could not empty the test session's Redis database ({e}).",
            file=sys.stderr,
        )


def start_redis_server(port):
    """Start a non-persistent ``redis-server`` on ``port`` and wait until it answers.

    The server runs in its own session, so a Ctrl+C in the terminal doesn't
    stop it before the experiment's server processes, which still need it
    while they shut down. The caller must stop it.

    Raises
    ------
    RuntimeError
        If the server exits (for example because the port is taken) or doesn't
        answer within 10 seconds.
    """
    if not _port_is_free(port):
        raise RuntimeError(f"Port {port} for a test Redis server is in use.")
    process = subprocess.Popen(
        ["redis-server", "--bind", "127.0.0.1", "--port", str(port)]
        + ["--dir", tempfile.gettempdir(), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1) as sock:
                    sock.sendall(b"PING\r\n")
                    if sock.recv(16).startswith(b"+PONG"):
                        return process
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"Redis on port {port} did not start.")
    except BaseException:
        _stop_process(process)
        raise


def _stop_process(process):
    """Terminate ``process``, killing it if it hasn't exited after 10 seconds."""
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _port_is_free(port):
    with socket.socket() as sock:
        # Servers bind with SO_REUSEADDR, so ports in TIME_WAIT are usable.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def lock_path(name):
    """Return the path of the lock file ``<name>.lock``.

    In ``/tmp`` rather than ``TMPDIR``, so that processes with different
    temporary directories still see each other's claims, like the
    development folders that are also in ``/tmp``.
    """
    root = "/tmp" if os.access("/tmp", os.W_OK) else tempfile.gettempdir()
    return os.path.join(root, f"{name}.lock")


def port_lock_path(port):
    """Return the lock file that a test session holds while it uses ``port``."""
    return lock_path(f"psynet-test-{port}")


def open_lock_file(path):
    """Open, creating if needed, the lock file at ``path`` without locking it.

    Another user's lock file is opened read-only, which is enough for
    ``flock``; such a lock file is not writable. Any local user can
    deliberately hold or block a lock name in ``/tmp``: these locks prevent
    accidents, not attacks.

    Raises
    ------
    OSError
        If the file can't be opened at all or isn't a regular file.
    """
    # Not following symlinks or truncating, so a link planted in /tmp
    # can't make this empty someone's file; non-blocking, so a FIFO can't hang.
    flags = os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | flags, 0o644)
        mode = "r+"
    except PermissionError:
        # Without O_CREAT, so Linux's fs.protected_regular allows it in /tmp.
        fd = os.open(path, os.O_RDONLY | flags)
        mode = "r"
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(f"{path} is not a regular file.")
    return os.fdopen(fd, mode)


def try_lock(path):
    """Take an exclusive lock on the file at ``path`` without waiting.

    Returns
    -------
    file or None
        The open lock file (see :func:`open_lock_file`), which holds the lock
        until it is closed, or None if another process holds the lock.

    Raises
    ------
    OSError
        If the file can't be opened at all or isn't a regular file.
    """
    lock = open_lock_file(path)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def _claim_port(start, also_free=None):
    """Return a free web port and an open lock file that reserves it.

    A test session's server binds its port only once the experiment has
    started, so the lock stops a second session from choosing the same port
    (and with it the same database) in the meantime. Closing the file releases
    the claim. ``also_free`` maps a candidate port to another port that must
    also be free, such as the session's Redis port.
    """
    for port in range(start, start + 1000, 10):
        try:
            lock = try_lock(port_lock_path(port))
        except OSError:
            # An unopenable claim file counts as taken.
            continue
        if lock is None:
            continue
        if _port_is_free(port) and (
            also_free is None or _port_is_free(also_free(port))
        ):
            return port, lock
        lock.close()
    raise RuntimeError(f"No free port found from {start}.")


def _spare_redis_database(redis_url, slot):
    """Return a Redis database number for session ``slot``, other than the shared one."""
    shared = int(urlsplit(redis_url).path.lstrip("/") or 0)
    numbers = [n for n in range(16) if n != shared]
    return numbers[slot % len(numbers)]


def _with_redis_database(redis_url, number):
    return urlunsplit(urlsplit(redis_url)._replace(path=f"/{number}"))
