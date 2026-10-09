"""Show which local PsyNet sessions use which ports, databases and Redis servers.

Several debug servers, test runs and CI slots can share one machine, each
with its own ``base_port``, ``DATABASE_URL`` and ``REDIS_URL``. Nothing
records those claims centrally: the running processes are the record. This
module reads them from the environments of the current user's PsyNet,
Dallinger, Flask and pytest processes, then matches them against the local
PostgreSQL databases and ``redis-server`` processes.

``psynet services list`` prints the result. With ``--clean`` it removes
leftovers of isolated test and debug sessions that have ended: databases named
``*_test_<port>``, ``*_debug_<port>`` or ``*_slot<n>``, ``redis-server``
processes that PsyNet started for such a session, and their emptied Redis
folders. It only touches resources that no running session references and,
for databases and Redis servers, that have no connections.

Unlike :mod:`psynet.services`, this module needs ``psutil`` and ``psycopg2``,
so it is imported lazily and needs ``psynet[experiment]``.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

import click

_DEFAULT_DATABASE_URL = "postgresql://dallinger:dallinger@localhost/dallinger"
_DEFAULT_REDIS_URL = "redis://localhost:6379"
_DEFAULT_BASE_PORT = "5000"
_SESSION_SCRIPTS = {"psynet", "dallinger", "pytest", "py.test", "flask"}
# Databases named by isolated test and debug sessions (with ports 5000-69999)
# and by CI slots, but not e.g. ``study_test_2024``.
_SESSION_DATABASE = re.compile(
    r"_((test|debug)_(?:[5-9]\d{3}|[1-6]\d{4})|slot\d{1,2})$"
)
_PYTHON_OPTIONS_WITH_VALUES = {"-W", "-X", "-Q"}
# Redis rewrites its command line to ``redis-server <host>:<port>``, so the
# folder it runs in is what identifies the servers that PsyNet started.
_REDIS_FOLDER = re.compile(r"psynet-(test|debug)-redis-\w+$")
# Set in the command that an isolated test or debug session reruns.
_ISOLATED_CHILD = "_PSYNET_TEST_ENVIRONMENT_READY"


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
    directory: str
    started_by_psynet: bool
    own: bool
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
            cwd = process.cwd()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if command[0] == "flask" and "base_port" not in environ:
            continue
        key = (
            environ.get("base_port", _DEFAULT_BASE_PORT),
            _database_name(environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)),
            _redis_port(environ.get("REDIS_URL", _DEFAULT_REDIS_URL)),
        )
        found.append((info, key, command, cwd, _ISOLATED_CHILD in environ))
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

    uid = os.getuid()
    servers = []
    for process in psutil.process_iter(["pid", "name", "uids", "cmdline"]):
        if process.info["name"] != "redis-server":
            continue
        cmdline = " ".join(process.info["cmdline"] or [])
        try:
            directory = process.cwd()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            directory = ""
        match = re.search(r"--port (\d+)|:(\d+)\s*$", cmdline)
        port = int(match.group(1) or match.group(2)) if match else None
        servers.append(
            RedisServer(
                pid=process.info["pid"],
                port=port,
                directory=directory,
                started_by_psynet=_is_session_redis_folder(directory),
                own=bool(process.info["uids"]) and process.info["uids"].real == uid,
                clients=_redis_clients(port) if port else None,
            )
        )
    return sorted(servers, key=lambda s: s.port or 0)


@contextmanager
def _cursor():
    """Yield an autocommit cursor on the ``DATABASE_URL`` server."""
    import psycopg2

    from .services import _postgres_url

    connection = psycopg2.connect(_postgres_url(), connect_timeout=3)
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


def _session_names(sessions, matches):
    """Return the sessions for which ``matches`` holds, e.g. ``session 5100``."""
    return ", ".join(f"session {s.base_port}" for s in sessions if matches(s))


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
        users = _session_names(sessions, lambda s: s.database == d.name)
        connections = _count(d.connections, "connection")
        click.echo(f"  {d.name}  {connections}  {users or 'no session'}")


def _count(number, noun):
    """Return e.g. ``1 connection`` or ``2 connections``."""
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _is_session_redis_folder(path):
    """Return whether ``path`` is a Redis folder of an isolated session."""
    return bool(path) and bool(_REDIS_FOLDER.match(os.path.basename(path)))


def find_redis_folders():
    """Return the current user's Redis folders of isolated sessions.

    Symbolic links are skipped, so cleaning never follows one out of the
    temporary directory.
    """
    root = tempfile.gettempdir()
    uid = os.getuid()
    folders = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not _REDIS_FOLDER.match(name):
            continue
        status = os.lstat(path)
        if stat.S_ISDIR(status.st_mode) and status.st_uid == uid:
            folders.append(path)
    return folders


def leftovers(sessions, redis_servers, databases, redis_folders=()):
    """Return the databases, Redis servers and Redis folders that ``--clean`` removes.

    A Redis folder is left over once no ``redis-server`` runs in it, for
    example after its session was killed with SIGKILL. No folder counts as
    left over while one of the user's Redis servers runs in an unknown folder.
    """
    used_databases = {s.database for s in sessions}
    used_redis_ports = {s.redis_port for s in sessions}
    stale_databases = [
        d
        for d in databases
        if _SESSION_DATABASE.search(d.name)
        and d.connections == 0
        and d.name not in used_databases
    ]
    stale_redis = [
        r
        for r in redis_servers
        if r.own
        and r.started_by_psynet
        and r.port not in used_redis_ports
        and r.clients == 0
    ]
    if any(r.own and not r.directory for r in redis_servers):
        return stale_databases, stale_redis, []
    running = {os.path.realpath(r.directory) for r in redis_servers if r.directory}
    stale_folders = [f for f in redis_folders if os.path.realpath(f) not in running]
    return stale_databases, stale_redis, stale_folders


def _redis_clients(port):
    """Return the number of other clients connected to Redis on ``port``.

    Returns ``None`` if the server doesn't answer, so it is never cleaned.
    """
    import redis

    try:
        info = redis.Redis(port=port, socket_timeout=2).info("clients")
    except redis.RedisError:
        return None
    return info["connected_clients"] - 1


def _clean(stale_databases, stale_redis, stale_folders):
    """Drop ``stale_databases``, stop ``stale_redis`` and remove ``stale_folders``."""
    import psutil
    from psycopg2 import Error as PostgresError
    from psycopg2 import sql

    if stale_databases:
        with _cursor() as cursor:
            for database in stale_databases:
                try:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {}").format(
                            sql.Identifier(database.name)
                        )
                    )
                except PostgresError as e:
                    click.echo(f"Could not drop database {database.name}: {e}")
                else:
                    click.echo(f"Dropped database {database.name}.")
    for server in stale_redis:
        try:
            process = psutil.Process(server.pid)
            if not _is_same_redis_server(process, server):
                click.echo(
                    f"Left PID {server.pid} running: it is no longer the "
                    f"redis-server on port {server.port}."
                )
                continue
            process.terminate()
            try:
                process.wait(timeout=10)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        except psutil.NoSuchProcess:
            click.echo(f"redis-server PID {server.pid} had already stopped.")
        else:
            click.echo(
                f"Stopped redis-server on port {server.port} (PID {server.pid})."
            )
        if _is_session_redis_folder(server.directory):
            stale_folders = [*stale_folders, server.directory]
    for folder in stale_folders:
        try:
            shutil.rmtree(folder)
        except OSError as e:
            click.echo(f"Could not remove Redis folder {folder}: {e}")
        else:
            click.echo(f"Removed Redis folder {folder}.")


def _is_same_redis_server(process, server):
    """Return whether ``process`` is still the ``redis-server`` listed as ``server``."""
    import psutil

    try:
        return process.name() == "redis-server" and os.path.realpath(
            process.cwd()
        ) == os.path.realpath(server.directory)
    except (psutil.AccessDenied, psutil.ZombieProcess):
        return False


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
    stale = leftovers(sessions, redis_servers, databases, find_redis_folders())
    stale_databases, stale_redis, stale_folders = stale
    if not any(stale):
        click.echo("\nNo leftovers of ended test or debug sessions to clean.")
        return
    click.echo("\nLeftovers of ended test and debug sessions:")
    for d in stale_databases:
        click.echo(f"  database {d.name}")
    for r in stale_redis:
        click.echo(f"  redis-server on port {r.port} (PID {r.pid})")
    for folder in stale_folders:
        click.echo(f"  Redis folder {folder}")
    if not assume_yes and not sys.stdin.isatty():
        raise click.ClickException(
            "Nobody can confirm the removal here; pass --yes to remove them."
        )
    if assume_yes or click.confirm("Remove them?", default=False):
        _clean(stale_databases, stale_redis, stale_folders)
