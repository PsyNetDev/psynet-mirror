"""Run local tests and debug servers in their own database, Redis, port and folder.

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
- the ``<database>_test_<port>`` database next to ``DATABASE_URL``, created if
  it is missing and reused by later sessions on the same port (tests reset its
  tables themselves);
- a private ``redis-server`` on the shared Redis port plus the same offset,
  stopped when the session ends (Redis delivers live notifications to every
  database on a server, so a database number on the shared server is only a
  fallback);
- its own ``dallinger_develop_directory``.

PsyNet's process cleanup already only targets processes that use the current
``DATABASE_URL`` (see ``psynet.command_line.uses_current_database``), so once
the URLs differ the tests leave a running ``psynet debug local`` alone.

Design constraints
------------------
Dallinger connects to PostgreSQL and Redis when ``dallinger.db`` is first
imported, so the environment variables must change before that import. This
module therefore imports nothing from Dallinger. It is used in these places:

- :mod:`psynet.pytest_environment`, an early pytest plugin that PsyNet's
  pytest configuration and the experiment ``pytest.ini`` template load with
  ``-p``. Plugins named with ``-p`` are imported before auto-loaded plugins
  such as ``pytest_dallinger`` and ``pytest_psynet``.
- ``psynet test local`` and ``psynet debug local --isolated``, which have
  already imported Dallinger by the time they run, and so re-run themselves
  in a child process inside the environment.

``PSYNET_TEST_ENVIRONMENT`` may be unset, ``isolated`` (the default) or
``shared`` (opt out); other values are an error, so a typo can't silently turn
isolation off. Sessions do nothing when :data:`READY_ENV_VAR` is set, which
marks the processes a session starts once their environment is chosen, or when
``CI`` is set, because CI machines run no debug server and their test slots
are isolated already.

``psynet debug local --isolated`` uses the same environment for a debug
server, with a ``<database>_debug_<port>`` database, so that several debug
servers and test sessions can run side by side. The database outlives the
server, so local commands such as ``psynet export local`` can still read it
with the ``DATABASE_URL`` that :meth:`IsolatedEnvironment.describe` prints; the
next debug server on that port resets it.

Isolation separates services, not files: tests still scaffold and remove
generated files in the experiment directory, so a ``psynet debug`` serving the
same directory breaks. :func:`check_no_debug_server` refuses to start in that
case.
"""

import fcntl
import os
import shutil
import socket
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
#: Purposes of an isolated environment; they name its database.
TEST = "test"
DEBUG = "debug"

DEFAULT_DATABASE_URL = "postgresql://dallinger:dallinger@localhost/dallinger"
DEFAULT_REDIS_URL = "redis://localhost:6379"
_DEFAULT_BASE_PORT = 5000
_PORT_OFFSET = 100


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


def _is_configured(environ):
    return bool(environ.get(READY_ENV_VAR) or environ.get("CI"))


def check_no_debug_server(directory, purpose=TEST):
    """Raise ``RuntimeError`` if another ``psynet debug`` process runs in ``directory``.

    Tests and debug servers replace the generated files in the experiment
    directory, which breaks a debug server that serves it, even when the
    services are isolated.
    """
    import psutil

    directory = os.path.realpath(directory)
    newcomer = "the tests" if purpose == TEST else "a second debug server"
    for process in psutil.process_iter(["cmdline", "cwd"]):
        cmdline = process.info["cmdline"] or []
        cwd = process.info["cwd"]
        if (
            process.pid != os.getpid()
            and cwd
            and os.path.realpath(cwd) == directory
            and _is_psynet_debug(cmdline)
        ):
            raise RuntimeError(
                f"psynet debug (PID {process.pid}) is serving {directory}, and "
                f"{newcomer} would replace its generated files. Stop it, or run "
                f"{newcomer} from a copy of the experiment such as a git worktree."
            )


def _is_psynet_debug(cmdline):
    return any(
        os.path.basename(arg) == "psynet" and cmdline[i + 1 : i + 2] == ["debug"]
        for i, arg in enumerate(cmdline)
    )


class IsolationError(RuntimeError):
    """Raised when a test session can't get its own database and Redis.

    The message gives the reason and how to opt out, so callers can show
    ``str(error)`` as is; the original exception is the ``__cause__``.
    """

    def __init__(self, reason, purpose=TEST):
        if purpose == DEBUG:
            message = (
                f"Could not give this debug server its own database and Redis "
                f"({reason}). Run it without --isolated to use the local ones."
            )
        else:
            message = (
                f"Could not give these tests their own database and Redis ({reason}). "
                f"Set {ENV_VAR}={SHARED} to run them against the local database and "
                "Redis instead, which resets any local debug server."
            )
        super().__init__(message)


class IsolatedEnvironment:
    """Environment variables for an isolated test session, plus its Redis server.

    Use :meth:`start` to create one and :meth:`close` (or a ``with`` block) to
    stop its Redis server.
    """

    def __init__(
        self, env, port_lock=None, redis_process=None, redis_dir=None, purpose=TEST
    ):
        self.env = env
        self.purpose = purpose
        self._port_lock = port_lock
        self._redis_process = redis_process
        self._redis_dir = redis_dir

    @classmethod
    def start(cls, environ=None, purpose=TEST):
        """Create the database and start Redis; return the new environment.

        ``purpose`` is :data:`TEST` or :data:`DEBUG`; the database is named
        ``<database>_<purpose>_<port>``.

        Raises
        ------
        IsolationError
            If no free port is found, PostgreSQL can't be reached, the
            database can't be created or Redis doesn't start; the message
            says how to opt out. Other errors propagate unchanged, because
            opting out would not fix them.
        """
        import psycopg2

        try:
            return cls._start(environ, purpose)
        except (OSError, RuntimeError, psycopg2.Error) as e:
            raise IsolationError(e, purpose) from e

    @classmethod
    def _start(cls, environ, purpose):
        environ = dict(os.environ if environ is None else environ)
        database_url = environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        redis_url = environ.get("REDIS_URL", DEFAULT_REDIS_URL)
        private_redis = shutil.which("redis-server") is not None
        shared_base_port = int(environ.get("base_port", _DEFAULT_BASE_PORT))
        shared_redis_port = urlsplit(redis_url).port or 6379

        def redis_port(web_port):
            # Offsetting from the claimed web port keeps concurrent sessions
            # from picking the same Redis port.
            return shared_redis_port + web_port - shared_base_port

        base_port, port_lock = _claim_port(
            shared_base_port + _PORT_OFFSET,
            also_free=redis_port if private_redis else None,
        )
        redis_dir = None
        try:
            env = {
                **environ,
                READY_ENV_VAR: "1",
                "DATABASE_URL": ensure_database(
                    database_url, suffix=f"_{purpose}_{base_port}"
                ),
                "base_port": str(base_port),
                "dallinger_develop_directory": f"/tmp/dallinger_develop_{base_port}",
            }
            if not private_redis:
                slot = (base_port - shared_base_port - _PORT_OFFSET) // 10
                number = _spare_redis_database(redis_url, slot)
                env["REDIS_URL"] = _with_redis_database(redis_url, number)
                print(
                    f"redis-server is not on PATH, so this session uses Redis "
                    f"database {number} on the shared server. Live notifications "
                    "can still reach another local debug server's participants.",
                    file=sys.stderr,
                )
                return cls(env, port_lock, purpose=purpose)

            redis_dir = tempfile.mkdtemp(prefix="psynet-test-redis-")
            process = start_redis_server(redis_port(base_port), redis_dir)
        except BaseException:
            if redis_dir is not None:
                shutil.rmtree(redis_dir, ignore_errors=True)
            port_lock.close()
            raise
        env["REDIS_URL"] = f"redis://127.0.0.1:{redis_port(base_port)}"
        return cls(env, port_lock, process, redis_dir, purpose)

    def describe(self):
        """Return a summary of where the session's services are."""
        database = urlsplit(self.env["DATABASE_URL"]).path.lstrip("/")
        if self.purpose == DEBUG:
            return (
                f"This debug server uses database {database}, Redis at "
                f"{self.env['REDIS_URL']} and port {self.env['base_port']}, so it "
                "runs alongside other local servers and tests. To point other "
                "local commands (such as psynet export local) at it, run:\n"
                f"  export DATABASE_URL={self.env['DATABASE_URL']} "
                f"REDIS_URL={self.env['REDIS_URL']} base_port={self.env['base_port']}\n"
                "Its Redis server stops with it, so after it stops export only "
                "DATABASE_URL."
            )
        return (
            f"PsyNet tests use database {database}, Redis at {self.env['REDIS_URL']} "
            f"and port {self.env['base_port']}, so they leave the services of local "
            f"debug servers alone (set {ENV_VAR}={SHARED} to share them instead)."
        )

    def close(self):
        """Stop the session's Redis server, if it started one."""
        if self._redis_process is not None:
            stop_process(self._redis_process)
            self._redis_process = None
        if self._redis_dir is not None:
            shutil.rmtree(self._redis_dir, ignore_errors=True)
            self._redis_dir = None
        if self._port_lock is not None:
            self._port_lock.close()
            self._port_lock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def ensure_database(database_url, *, suffix, fresh=False):
    """Create ``<database><suffix>`` next to ``database_url`` and return its URL.

    With ``fresh=True`` an existing database is dropped first, after
    terminating its connections.
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
            if fresh:
                # DROP DATABASE ... WITH (FORCE) needs PostgreSQL 13, but
                # `psynet services ensure` starts PostgreSQL 12.
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
                )
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                )
    finally:
        connection.close()
    return urlunsplit(parts._replace(path=f"/{name}"))


def start_redis_server(port, directory, log_file=None):
    """Start a non-persistent ``redis-server`` on ``port`` and wait until it answers.

    Raises
    ------
    RuntimeError
        If the server exits (for example because the port is taken) or doesn't
        answer within 10 seconds.
    """
    if not _port_is_free(port):
        raise RuntimeError(f"Port {port} for a test Redis server is in use.")
    # In its own session, Ctrl+C in the terminal doesn't stop Redis before the
    # servers that use it; the session's owner stops it afterwards.
    process = subprocess.Popen(
        ["redis-server", "--bind", "127.0.0.1", "--port", str(port)]
        + ["--dir", str(directory), "--save", "", "--appendonly", "no"],
        stdout=log_file or subprocess.DEVNULL,
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
        stop_process(process)
        raise


def stop_process(process):
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
            lock = open(
                os.path.join(tempfile.gettempdir(), f"psynet-test-{port}.lock"), "w"
            )
        except OSError:
            continue
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
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
