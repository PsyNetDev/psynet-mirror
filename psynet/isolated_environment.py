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
- the ``<database>_test_<port>`` database next to ``DATABASE_URL``, created
  afresh when the session starts and dropped when it ends;
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
servers and test sessions can run side by side. Like test databases, it is
dropped when the server stops, so local commands such as ``psynet export
local`` must read it, with the ``DATABASE_URL`` that
:meth:`IsolatedEnvironment.describe` prints, while the server runs.

Isolation separates services, not files: tests still scaffold and remove
generated files in the experiment directory, so a ``psynet debug`` serving the
same directory breaks. :func:`check_no_debug_server` refuses to start in that
case.
"""

import ctypes
import fcntl
import os
import re
import shlex
import shutil
import signal
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
_PR_SET_PDEATHSIG = 1


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
    in_ci = environ.get("CI", "").lower() not in ("", "0", "false")
    return bool(environ.get(READY_ENV_VAR)) or in_ci


def check_no_debug_server(directory, purpose=TEST):
    """Raise ``RuntimeError`` if another ``psynet debug`` process runs in ``directory``.

    Tests and debug servers replace the generated files in the experiment
    directory, which breaks a debug server that serves it, even when the
    services are isolated. Servers that a test session started there are
    skipped: that session holds the directory's lock, which tests wait for.
    """
    import psutil

    from .testing.locks import HELD_LOCK_ENV_VAR

    newcomer = "the tests" if purpose == TEST else "a second debug server"
    directory = os.path.realpath(directory)
    for process in _debug_servers(directory):
        try:
            held_lock = process.environ().get(HELD_LOCK_ENV_VAR)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            held_lock = None
        if held_lock is not None and os.path.realpath(held_lock) == directory:
            continue
        raise RuntimeError(
            f"psynet debug (PID {process.pid}) is serving {directory}, and "
            f"{newcomer} would replace its generated files. Stop it, or run "
            f"{newcomer} from a copy of the experiment such as a git worktree."
        )


def debug_server_environment(directory):
    """Return the PID and environment of the ``psynet debug`` serving ``directory``.

    For ``psynet debug local --isolated`` this is the re-run child, whose
    environment holds the server's own settings. Returns ``None`` if no debug
    server runs there or its environment can't be read.
    """
    import psutil

    found = None
    for process in _debug_servers(directory):
        try:
            environ = process.environ()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        if found is None or READY_ENV_VAR in environ:
            found = process.pid, environ
    return found


def _debug_servers(directory):
    """Yield the ``psynet debug`` processes in ``directory``, except this command."""
    import psutil

    directory = os.path.realpath(directory)
    # Wrappers such as ``timeout 60 psynet debug local`` are this command itself.
    this_command = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
    for process in psutil.process_iter(["cmdline", "cwd"]):
        cwd = process.info["cwd"]
        if (
            process.pid not in this_command
            and cwd
            and os.path.realpath(cwd) == directory
            and _is_psynet_debug(process.info["cmdline"] or [])
        ):
            yield process


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
                f"({reason}). Without --isolated it uses the local ones instead, "
                "which resets them and stops any other local debug server that uses them."
            )
        else:
            message = (
                f"Could not give these tests their own database and Redis ({reason}). "
                f"Set {ENV_VAR}={SHARED} to run them against the local database and "
                "Redis instead, which resets any local debug server."
            )
        super().__init__(message)


def is_isolated_debug_server(environ):
    """Return whether ``environ`` is that of a ``psynet debug local --isolated``."""
    database = urlsplit(environ.get("DATABASE_URL", "")).path
    return bool(environ.get(READY_ENV_VAR)) and database.endswith(
        f"_{DEBUG}_{environ.get('base_port')}"
    )


_SERVER_SETTINGS = ("DATABASE_URL", "REDIS_URL", "base_port")


def export_advice(environ):
    """Return how to point other local commands at the debug server with ``environ``.

    Settings the server has are exported and those it lacks are unset, so the
    line also works for a plain ``psynet debug local``.
    """
    advice = (
        "To point other local commands (such as psynet export local) at it, run:\n"
        f"  {_export_line(environ)}"
    )
    if is_isolated_debug_server(environ):
        advice += "\nExport what you need while it runs: its database is dropped when it stops."
    return advice


def _export_line(environ):
    exported = [
        f"{k}={shlex.quote(environ[k])}" for k in _SERVER_SETTINGS if k in environ
    ]
    unset = [k for k in _SERVER_SETTINGS if k not in environ]
    commands = []
    if exported:
        commands.append("export " + " ".join(exported))
    if unset:
        commands.append("unset " + " ".join(unset))
    return "; ".join(commands)


class IsolatedEnvironment:
    """Environment variables for an isolated test session, plus its Redis server.

    Use :meth:`start` to create one and :meth:`close` (or a ``with`` block) to
    stop its Redis server.
    """

    def __init__(
        self,
        env,
        port_lock=None,
        redis_process=None,
        purpose=TEST,
    ):
        self.env = env
        self.purpose = purpose
        self._port_lock = port_lock
        self._redis_process = redis_process

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
        environ = without_session_settings(
            dict(os.environ if environ is None else environ)
        )
        database_url = environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        private_redis = shutil.which("redis-server") is not None

        def usable(port):
            return not private_redis or _port_is_free(
                _session_redis_port(environ, port)
            )

        base_port, port_lock = _claim_port(
            _shared_base_port(environ) + _PORT_OFFSET, usable=usable
        )
        try:
            env = {
                **environ,
                READY_ENV_VAR: "1",
                "DATABASE_URL": create_database(
                    database_url, suffix=f"_{purpose}_{base_port}"
                ),
                "REDIS_URL": _session_redis_url(environ, base_port, private_redis),
                "base_port": str(base_port),
                # Not gettempdir(): Dallinger rejects development paths with a period.
                "dallinger_develop_directory": f"/tmp/dallinger_develop_{base_port}",
            }
            if not private_redis:
                print(
                    f"redis-server is not on PATH, so this session uses "
                    f"{env['REDIS_URL']} on the shared server. Live notifications "
                    "can still reach another local debug server's participants.",
                    file=sys.stderr,
                )
                return cls(env, port_lock, purpose=purpose)

            process = start_redis_server(
                _session_redis_port(environ, base_port),
                tempfile.gettempdir(),
                stop_with_caller=True,
            )
        except BaseException:
            port_lock.close()
            raise
        return cls(env, port_lock, process, purpose)

    def describe(self):
        """Return a summary of where the session's services are."""
        database = urlsplit(self.env["DATABASE_URL"]).path.lstrip("/")
        if self.purpose == DEBUG:
            return (
                f"This debug server uses database {database}, Redis at "
                f"{self.env['REDIS_URL']} and port {self.env['base_port']}, so it "
                "runs alongside other local servers and tests.\n"
                + export_advice(self.env)
            )
        return (
            f"PsyNet tests use database {database}, Redis at {self.env['REDIS_URL']} "
            f"and port {self.env['base_port']}, so they leave the services of local "
            f"debug servers alone (set {ENV_VAR}={SHARED} to share them instead)."
        )

    def stopped_message(self):
        """Return what to tell the user once a debug server has stopped."""
        database = urlsplit(self.env["DATABASE_URL"]).path.lstrip("/")
        return (
            f"The debug server on port {self.env['base_port']} has stopped. Its "
            f"database {database} and Redis server were removed with it."
        )

    def close(self):
        """Stop the session's Redis server and drop its database."""
        if self._redis_process is not None:
            stop_process(self._redis_process)
            self._redis_process = None
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


def without_session_settings(environ):
    """Return ``environ`` without the exported settings of an isolated session.

    A shell that ran the ``export`` line of a debug server has its
    ``<database>_debug_<port>`` database, its private Redis (which stops with
    the server) and its port. A new session should start from the shared
    settings instead, not from databases such as
    ``dallinger_debug_5100_test_5200`` and a stopped Redis.
    """
    environ = dict(environ)
    parts = urlsplit(environ.get("DATABASE_URL", ""))
    path = re.sub(rf"_({TEST}|{DEBUG})_\d+$", "", parts.path)
    if path != parts.path:
        environ["DATABASE_URL"] = urlunsplit(parts._replace(path=path))
        environ.pop("REDIS_URL", None)
        environ.pop("base_port", None)
    return environ


def _shared_base_port(environ):
    return int(environ.get("base_port", _DEFAULT_BASE_PORT))


def _session_redis_port(environ, port):
    # Offsetting from the claimed web port keeps concurrent sessions from
    # picking the same Redis port.
    shared_redis_port = urlsplit(environ.get("REDIS_URL", DEFAULT_REDIS_URL)).port
    return (shared_redis_port or 6379) + port - _shared_base_port(environ)


def _session_redis_url(environ, port, private_redis):
    """Return the Redis URL of the session on web ``port``."""
    if private_redis:
        return f"redis://127.0.0.1:{_session_redis_port(environ, port)}"
    redis_url = environ.get("REDIS_URL", DEFAULT_REDIS_URL)
    slot = (port - _shared_base_port(environ) - _PORT_OFFSET) // 10
    return _with_redis_database(redis_url, _spare_redis_database(redis_url, slot))


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

    # DROP DATABASE ... WITH (FORCE) needs PostgreSQL 13, but
    # `psynet services ensure` starts PostgreSQL 12.
    cursor.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (name,),
    )
    cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def _drop_session_database(session_database_url):
    """Drop a session's database, warning instead of raising if that fails."""
    import psycopg2

    shared_url = without_session_settings({"DATABASE_URL": session_database_url})[
        "DATABASE_URL"
    ]
    name = urlsplit(session_database_url).path.lstrip("/")
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


def start_redis_server(port, directory, log_file=None, stop_with_caller=False):
    """Start a non-persistent ``redis-server`` on ``port`` and wait until it answers.

    With ``stop_with_caller=True`` the server runs in its own session, so
    Ctrl+C in the terminal doesn't stop it before the servers that use it, and
    stops when the calling process dies without cleaning up; see
    :func:`sigterm_on_caller_exit`. Otherwise it stays in the caller's process
    group and gets its signals.

    Raises
    ------
    RuntimeError
        If the server exits (for example because the port is taken) or doesn't
        answer within 10 seconds.
    """
    if not _port_is_free(port):
        raise RuntimeError(f"Port {port} for a session's Redis server is in use.")
    process = subprocess.Popen(
        ["redis-server", "--bind", "127.0.0.1", "--port", str(port)]
        + ["--dir", str(directory), "--save", "", "--appendonly", "no"],
        stdout=log_file or subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=stop_with_caller,
        preexec_fn=sigterm_on_caller_exit() if stop_with_caller else None,
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


def sigterm_on_caller_exit():
    """Return a ``preexec_fn`` that sends the child SIGTERM when the caller dies.

    This stops a session's Redis server and re-run command even when the
    process that started them is killed with SIGKILL and can't clean up. It
    uses Linux's ``PR_SET_PDEATHSIG``, which fires when the calling *thread*
    exits, so call it from a thread that lives as long as the session. Returns
    ``None`` on other platforms.
    """
    if not sys.platform.startswith("linux"):
        return None
    prctl = ctypes.CDLL(None, use_errno=True).prctl
    caller = os.getpid()

    def preexec():
        # The caller may already have died between fork and prctl.
        if prctl(_PR_SET_PDEATHSIG, signal.SIGTERM) != 0 or os.getppid() != caller:
            os.kill(os.getpid(), signal.SIGTERM)

    return preexec


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


def port_lock_path(port):
    """Return the lock file that a test or debug session holds while it uses ``port``.

    In ``/tmp`` rather than ``TMPDIR``, so that sessions with different
    temporary directories still see each other's claims, like the
    development folders that are also in ``/tmp``.
    """
    root = "/tmp" if os.access("/tmp", os.W_OK) else tempfile.gettempdir()
    return os.path.join(root, f"psynet-test-{port}.lock")


def _claim_port(start, usable=None):
    """Return a free web port and an open lock file that reserves it.

    A test session's server binds its port only once the experiment has
    started, so the lock stops a second session from choosing the same port
    (and with it the same database) in the meantime. Closing the file releases
    the claim. ``usable`` says whether a candidate port can be used besides
    being free, for example because the session's Redis port is also free.
    """
    for port in range(start, start + 1000, 10):
        try:
            # Not following symlinks or truncating, so a link planted in /tmp
            # can't make this empty someone's file.
            fd = os.open(
                port_lock_path(port), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644
            )
        except OSError:
            continue
        lock = os.fdopen(fd, "r+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            continue
        if _port_is_free(port) and (usable is None or usable(port)):
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
