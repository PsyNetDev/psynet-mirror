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

``psynet services list`` prints the result. It only reads; it never stops
processes or drops databases.

Unlike :mod:`psynet.services`, this module needs ``psutil`` and ``psycopg2``,
so it is imported lazily and needs ``psynet[experiment]``.
"""

from __future__ import annotations

import fcntl
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

import click

from .isolated_environment import (
    DEFAULT_DATABASE_URL,
    DEFAULT_REDIS_URL,
    READY_ENV_VAR,
    port_lock_path,
    split_session_database,
)

_DEFAULT_BASE_PORT = "5000"
_SESSION_SCRIPTS = {"psynet", "dallinger", "pytest", "py.test", "flask"}
_PYTHON_OPTIONS_WITH_VALUES = {"-W", "-X"}


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
    """Yield a cursor on the ``postgres`` database of ``DATABASE_URL``'s server."""
    import psycopg2

    from .services import _postgres_url

    url = urlparse(_postgres_url())._replace(path="/postgres").geturl()
    connection = psycopg2.connect(url, connect_timeout=3)
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


def _port_is_claimed(port):
    """Return whether an isolated session holds the lock of ``port``."""
    try:
        lock = os.fdopen(os.open(port_lock_path(port), os.O_RDONLY | os.O_NOFOLLOW))
    except OSError:
        return False
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
    return False


def _session_names(sessions, matches):
    """Return the sessions for which ``matches`` holds, e.g. ``session 5100``."""
    return ", ".join(f"session {s.base_port}" for s in sessions if matches(s))


def _database_users(database, sessions):
    """Describe who uses ``database``, e.g. ``session 5100`` or ``no session``."""
    users = _session_names(sessions, lambda s: s.database == database.name)
    _, port = split_session_database(database.name)
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


def list_services():
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
