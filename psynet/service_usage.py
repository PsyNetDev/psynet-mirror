"""Show which local PsyNet sessions use which ports, databases and Redis servers.

Several debug servers, test runs and CI slots can share one machine, each
with its own ``base_port``, ``DATABASE_URL`` and ``REDIS_URL``. Nothing
records those claims centrally: the running processes are the record. This
module reads them from the environments of the current user's PsyNet,
Dallinger, Flask and pytest processes, then matches them against the local
PostgreSQL databases and ``redis-server`` processes.

A process's environment shows only the settings it started with. Isolated
sessions under plain ``pytest`` change theirs in-process (see
:mod:`psynet.isolated_environment`), so the port lock that every isolated test
and debug session holds is the reliable sign that its database is in use.

``psynet services list`` prints the result. With ``--clean`` it drops the
databases of isolated sessions that were killed before they could drop them
themselves: those named ``<base>_test_<port>`` and ``<base>_debug_<port>``,
where ``<base>`` is ``dallinger`` or this shell's database. It never stops
processes, and it skips databases with connections, databases that a visible
session or this shell uses, and databases whose port lock is held, which it
holds itself while dropping. It
only cleans a local PostgreSQL server, because the port locks and processes
it checks are this machine's. CI slot databases (``*_slot<n>``) are left
alone: ``psynet dev ci run-tests`` reuses them and holds no lock between
test items.

Unlike :mod:`psynet.services`, this module needs ``psutil`` and ``psycopg2``,
so it is imported lazily and needs ``psynet[experiment]``.
"""

from __future__ import annotations

import fcntl
import os
import re
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

import click

from .isolated_environment import (
    DEBUG,
    DEFAULT_DATABASE_URL,
    DEFAULT_REDIS_URL,
    READY_ENV_VAR,
    TEST,
    port_lock_path,
)

_DEFAULT_BASE_PORT = "5000"
_SESSION_SCRIPTS = {"psynet", "dallinger", "pytest", "py.test", "flask"}
_ISOLATED_DATABASE = re.compile(rf"(\w+)_({TEST}|{DEBUG})_(\d{{4,5}})")
# Session ports start at 5000, so that names such as ``study_test_2024`` don't match.
_SESSION_PORTS = range(5000, 65536)
_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
_PYTHON_OPTIONS_WITH_VALUES = {"-W", "-X", "-Q"}


@dataclass
class Session:
    """Processes that share one ``base_port``, database and Redis."""

    base_port: str
    database: str
    redis_port: int
    pids: list[int] = field(default_factory=list)
    command: str = ""
    directory: str = ""


@dataclass
class RedisServer:
    """A running ``redis-server`` process."""

    pid: int
    port: int | None
    #: Other connected clients, or ``None`` if the server didn't answer.
    clients: int | None = None


@dataclass
class Database:
    """A PostgreSQL database and its open connection count."""

    name: str
    connections: int


def _session_command(cmdline):
    """Return a command line's script and arguments, e.g. ``psynet debug local``.

    Handles both scripts run directly and ``python [options] -m pytest``.
    Returns ``None`` for commands other than PsyNet, Dallinger, Flask and pytest.
    """
    args = list(cmdline)
    if args and os.path.basename(args[0]).startswith("python"):
        args.pop(0)
        while args and args[0].startswith("-"):
            option = args.pop(0)
            if option == "-m":
                break
            if option in _PYTHON_OPTIONS_WITH_VALUES and args:
                args.pop(0)
    if not args:
        return None
    name = os.path.basename(args[0])
    if name in _SESSION_SCRIPTS or name.startswith("dallinger_heroku_"):
        return [name, *args[1:]]
    return None


def _redis_port(url):
    """Return the port of a Redis URL, or ``None`` if it cannot be parsed."""
    try:
        return urlparse(url).port or 6379
    except ValueError:
        return None


def _database_name(url):
    """Return the database name in a PostgreSQL URL."""
    return urlparse(url).path.lstrip("/")


def find_sessions():
    """Return the current user's PsyNet sessions, keyed by their shared settings."""
    import psutil

    uid, own_pid = os.getuid(), os.getpid()
    found = []
    for process in psutil.process_iter(["pid", "ppid", "uids", "cmdline"]):
        info = process.info
        if not info["uids"] or info["uids"].real != uid or info["pid"] == own_pid:
            continue
        command = _session_command(info["cmdline"] or [])
        if command is None:
            continue
        try:
            environ = process.environ()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        try:
            cwd = process.cwd()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            cwd = ""
        if command[0] == "flask" and "base_port" not in environ:
            continue
        key = (
            environ.get("base_port", _DEFAULT_BASE_PORT),
            _database_name(environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)),
            _redis_port(environ.get("REDIS_URL", DEFAULT_REDIS_URL)),
        )
        found.append((info, key, command, cwd, READY_ENV_VAR in environ))
    # An isolated launcher keeps the caller's settings but only waits for its
    # rerun child, so it belongs to the child's session.
    child_keys = {info["ppid"]: key for info, key, *_, child in found if child}
    sessions = {}
    for info, key, command, cwd, child in found:
        if not child:
            key = child_keys.get(info["pid"], key)
        session = sessions.setdefault(key, Session(*key))
        session.pids.append(info["pid"])
        if not session.command:
            session.command = " ".join(command)[:80]
            session.directory = cwd
    for session in sessions.values():
        session.pids.sort()
    return sorted(sessions.values(), key=lambda s: (s.base_port.zfill(6), s.database))


def find_redis_servers():
    """Return all running ``redis-server`` processes."""
    import psutil

    servers = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        if process.info["name"] != "redis-server":
            continue
        cmdline = " ".join(process.info["cmdline"] or [])
        match = re.search(r"--port (\d+)|:(\d+)\s*$", cmdline)
        port = int(match.group(1) or match.group(2)) if match else None
        servers.append(
            RedisServer(
                pid=process.info["pid"],
                port=port,
                clients=_redis_clients(port) if port else None,
            )
        )
    return sorted(servers, key=lambda s: s.port or 0)


@contextmanager
def _cursor():
    """Yield an autocommit cursor on the ``postgres`` database of ``DATABASE_URL``'s server.

    Not on ``DATABASE_URL``'s own database, which could be one to drop.
    """
    import psycopg2

    from .services import _postgres_url

    url = urlparse(_postgres_url())._replace(path="/postgres").geturl()
    connection = psycopg2.connect(url, connect_timeout=3)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            yield cursor
    finally:
        connection.close()


def find_databases():
    """Return the non-template databases with their open connection counts."""
    with _cursor() as cursor:
        cursor.execute(
            "SELECT d.datname, count(a.pid) FROM pg_database d "
            "LEFT JOIN pg_stat_activity a "
            "ON a.datname = d.datname AND a.pid <> pg_backend_pid() "
            "WHERE NOT d.datistemplate AND d.datname <> 'postgres' "
            "GROUP BY d.datname ORDER BY d.datname"
        )
        return [Database(name, count) for name, count in cursor.fetchall()]


def _isolated_database(database_name):
    """Return ``(base, purpose, port)`` for an isolated session's database, or ``None``."""
    match = _ISOLATED_DATABASE.fullmatch(database_name)
    if not match or int(match.group(3)) not in _SESSION_PORTS:
        return None
    return match.group(1), match.group(2), int(match.group(3))


def _session_port(database_name):
    """Return the port in an isolated session's database name, or ``None``."""
    parts = _isolated_database(database_name)
    return parts[2] if parts else None


def _base_database(database_name):
    """Return the database that an isolated session's database was named after."""
    parts = _isolated_database(database_name)
    return parts[0] if parts else database_name


def _open_lock(path):
    """Open a lock file read-only, creating it if missing, without following symlinks.

    ``flock`` works on read-only files, and opening another user's existing
    file without ``O_CREAT`` passes Linux's ``protected_regular`` check.
    """
    try:
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return os.open(path, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644)


@contextmanager
def _port_claim(port):
    """Yield whether the lock of ``port`` was free, holding it until exit if so.

    Yields ``None`` if the lock file can't be opened, for example because it
    is a symbolic link.
    """
    try:
        lock = os.fdopen(_open_lock(port_lock_path(port)))
    except OSError:
        yield None
        return
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
        else:
            yield True


def _port_is_claimed(port):
    """Return whether the lock of ``port`` is held, or can't be checked."""
    if not os.path.lexists(port_lock_path(port)):
        return False
    with _port_claim(port) as free:
        return free is not True


def _session_names(sessions, matches):
    """Return the sessions for which ``matches`` holds, e.g. ``session 5100``."""
    return ", ".join(f"session {s.base_port}" for s in sessions if matches(s))


def _database_users(database, sessions):
    """Describe who uses ``database``, e.g. ``session 5100`` or ``no session``."""
    users = _session_names(sessions, lambda s: s.database == database.name)
    port = _session_port(database.name)
    if not users and port is not None and _port_is_claimed(port):
        users = f"a session holding port {port}"
    return users or "no session"


def _report(sessions, redis_servers, databases):
    """Print sessions, Redis servers and databases with who uses them."""
    click.echo("Sessions (base_port, database, Redis port, directory):")
    if not sessions:
        click.echo("  none")
    for s in sessions:
        click.echo(
            f"  {s.base_port}  {s.database}  {s.redis_port}  {s.directory}\n"
            f"        {s.command} (PIDs {', '.join(map(str, s.pids))})"
        )
    click.echo("\nRedis servers:")
    for r in redis_servers:
        users = _session_names(sessions, lambda s: s.redis_port == r.port)
        clients = "no answer" if r.clients is None else _count(r.clients, "client")
        click.echo(f"  {r.port}  PID {r.pid}  {clients}  {users or 'no session'}")
    click.echo("\nDatabases:")
    for d in databases:
        connections = _count(d.connections, "connection")
        click.echo(f"  {d.name}  {connections}  {_database_users(d, sessions)}")


def _count(number, noun):
    """Return e.g. ``1 connection`` or ``2 connections``."""
    return f"{number} {noun}{'' if number == 1 else 's'}"


def leftovers(sessions, databases, *, in_use=(), bases=("dallinger",)):
    """Return the databases that ``--clean`` drops.

    ``in_use`` names further databases to keep, such as this shell's own.
    Only isolated databases named after one of ``bases`` count, so that a
    look-alike such as ``booking_test_6000`` is kept.
    """
    used = {s.database for s in sessions} | set(in_use)
    stale = []
    for d in databases:
        parts = _isolated_database(d.name)
        if parts is None or parts[0] not in bases:
            continue
        if d.connections == 0 and d.name not in used:
            stale.append(d)
    return stale


def _redis_clients(port):
    """Return the number of other clients connected to Redis on ``port``.

    Returns ``None`` if the server doesn't answer.
    """
    import redis

    try:
        info = redis.Redis(port=port, socket_timeout=2).info("clients")
    except redis.RedisError:
        return None
    return info["connected_clients"] - 1


def _clean(stale_databases):
    """Drop ``stale_databases`` and return the number of failures.

    A database whose port lock a session has claimed meanwhile is kept; the
    lock is held while dropping, so no session can claim it halfway.
    """
    from psycopg2 import Error as PostgresError
    from psycopg2 import sql

    failures = 0
    if stale_databases:
        with _cursor() as cursor:
            for database in stale_databases:
                port = _session_port(database.name)
                with ExitStack() as stack:
                    free = port is None or stack.enter_context(_port_claim(port))
                    if free is None:
                        click.echo(
                            f"Kept database {database.name}: can't open the "
                            f"lock file {port_lock_path(port)}."
                        )
                        continue
                    if not free:
                        click.echo(
                            f"Kept database {database.name}: a session now "
                            f"holds port {port}."
                        )
                        continue
                    try:
                        cursor.execute(
                            sql.SQL("DROP DATABASE {}").format(
                                sql.Identifier(database.name)
                            )
                        )
                    except PostgresError as e:
                        failures += 1
                        click.echo(f"Could not drop database {database.name}: {e}")
                    else:
                        click.echo(f"Dropped database {database.name}.")
    return failures


def _find_leftovers():
    """Return the databases ``--clean`` would drop now, skipping claimed session ports."""
    own = _database_name(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    bases = {_database_name(DEFAULT_DATABASE_URL), _base_database(own)}
    stale = leftovers(find_sessions(), find_databases(), in_use={own}, bases=bases)
    return [
        d
        for d in stale
        if _session_port(d.name) is None or not _port_is_claimed(_session_port(d.name))
    ]


def list_services(*, clean_leftovers, assume_yes):
    """Implement ``psynet services list``."""
    try:
        import psutil  # noqa: F401
        import psycopg2
    except ImportError as e:
        raise click.ClickException(
            "'psynet services list' needs psynet[experiment]; run 'psynet setup' first."
        ) from e
    sessions = find_sessions()
    redis_servers = find_redis_servers()
    try:
        databases = find_databases()
    except psycopg2.Error as e:
        databases = None
        database_error = str(e).strip()
    _report(sessions, redis_servers, databases or [])
    if databases is None:
        click.echo(f"  could not list them: {database_error}")
        if clean_leftovers:
            raise click.ClickException("--clean needs PostgreSQL to be reachable.")
    if not clean_leftovers:
        return
    host = _database_host()
    if host not in _LOCAL_HOSTS and not host.startswith("/"):
        raise click.ClickException(
            f"--clean only cleans a local PostgreSQL server, but DATABASE_URL "
            f"points at {host}, whose other users this computer can't see."
        )
    try:
        _clean_interactively(assume_yes)
    except psycopg2.Error as e:
        raise click.ClickException(f"PostgreSQL failed while cleaning: {e}") from e


def _database_host():
    """Return the host of the PostgreSQL server that ``DATABASE_URL`` names."""
    from .services import _postgres_url

    return urlparse(_postgres_url()).hostname or ""


def _clean_interactively(assume_yes):
    """List the leftover databases, ask for confirmation, then drop those still left over."""
    stale = _find_leftovers()
    if not stale:
        click.echo("\nNo databases of ended test or debug sessions to drop.")
        return
    click.echo("\nDatabases of ended test and debug sessions:")
    for d in stale:
        click.echo(f"  {d.name}")
    if not assume_yes and not sys.stdin.isatty():
        raise click.ClickException(
            "Nobody can confirm dropping them here; pass --yes to drop them."
        )
    if not (assume_yes or click.confirm("Drop them?", default=False)):
        return
    # Sessions may have started while the question was open.
    now_names = {d.name for d in _find_leftovers()}
    failures = _clean([d for d in stale if d.name in now_names])
    if failures:
        raise click.ClickException(
            f"{_count(failures, 'database')} could not be dropped."
        )
