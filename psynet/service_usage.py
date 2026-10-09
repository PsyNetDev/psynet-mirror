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

``psynet services list`` prints the result. With ``--clean`` it removes
leftovers of isolated sessions that have ended: databases named
``*_test_<port>`` or ``*_slot<n>`` (and, if asked, ``*_debug_<port>``) and
Redis folders that no ``redis-server`` runs in. It never stops processes, and
it skips databases with connections, databases that a visible session or this
shell uses, and databases whose port lock is held, which it holds itself
while dropping.

Unlike :mod:`psynet.services`, this module needs ``psutil`` and ``psycopg2``,
so it is imported lazily and needs ``psynet[experiment]``.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import stat
import sys
import tempfile
import time
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
# Ports 5000-69999, so that names such as ``study_test_2024`` don't match.
_SESSION_PORT = r"(?:[5-9]\d{3}|[1-6]\d{4})"
_ISOLATED_DATABASE = re.compile(rf"_({TEST}|{DEBUG})_({_SESSION_PORT})$")
_SLOT_DATABASE = re.compile(r"_slot\d{1,2}$")
_PYTHON_OPTIONS_WITH_VALUES = {"-W", "-X", "-Q"}
# Redis rewrites its command line to ``redis-server <host>:<port>``, so the
# folder it runs in is what ties a server to an isolated session.
_REDIS_FOLDER = re.compile(rf"psynet-({TEST}|{DEBUG})-redis-\w+$")
# A session creates its Redis folder just before starting Redis in it.
_REDIS_FOLDER_GRACE_SECONDS = 60


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
                own=bool(process.info["uids"]) and process.info["uids"].real == uid,
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


def _session_port(database_name):
    """Return the port in an isolated session's database name, or ``None``."""
    match = _ISOLATED_DATABASE.search(database_name)
    return int(match.group(2)) if match else None


@contextmanager
def _port_claim(port):
    """Yield whether the lock of ``port`` was free, holding it until exit if so."""
    try:
        lock = open(port_lock_path(port), "a")
    except OSError:
        yield False
        return
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
        else:
            yield True


def _port_is_claimed(port):
    """Return whether a running isolated session holds the lock of ``port``."""
    if not os.path.exists(port_lock_path(port)):
        return False
    with _port_claim(port) as free:
        return not free


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


def find_redis_folders():
    """Return the current user's Redis folders of isolated sessions.

    Symbolic links are skipped, so cleaning never follows one out of the
    temporary directory, as are folders created in the last minute, whose
    session may be about to start Redis in them.
    """
    root = tempfile.gettempdir()
    uid = os.getuid()
    folders = []
    for name in sorted(os.listdir(root)):
        if not _REDIS_FOLDER.match(name):
            continue
        path = os.path.join(root, name)
        try:
            status = os.lstat(path)
        except FileNotFoundError:
            continue
        if (
            stat.S_ISDIR(status.st_mode)
            and status.st_uid == uid
            and time.time() - status.st_mtime > _REDIS_FOLDER_GRACE_SECONDS
        ):
            folders.append(path)
    return folders


def leftovers(
    sessions,
    redis_servers,
    databases,
    redis_folders=(),
    *,
    include_debug_data=False,
    in_use=(),
):
    """Return the databases and Redis folders that ``--clean`` removes.

    ``in_use`` names further databases to keep, such as this shell's own.
    Debug databases are kept for ``psynet export local`` unless
    ``include_debug_data`` is set. A Redis folder is left over once no
    ``redis-server`` runs in it, for example after its session was killed
    with SIGKILL. No folder counts as left over while one of the user's Redis
    servers runs in an unknown folder.
    """
    used = {s.database for s in sessions} | set(in_use)
    stale_databases = []
    for d in databases:
        match = _ISOLATED_DATABASE.search(d.name)
        if not (match or _SLOT_DATABASE.search(d.name)):
            continue
        if match and match.group(1) == DEBUG and not include_debug_data:
            continue
        if d.connections == 0 and d.name not in used:
            stale_databases.append(d)
    if any(r.own and not r.directory for r in redis_servers):
        return stale_databases, []
    running = {os.path.realpath(r.directory) for r in redis_servers if r.directory}
    stale_folders = [f for f in redis_folders if os.path.realpath(f) not in running]
    return stale_databases, stale_folders


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


def _clean(stale_databases, stale_folders):
    """Drop ``stale_databases`` and remove ``stale_folders``.

    A database whose port lock a session has claimed meanwhile is kept; the
    lock is held while dropping, so no session can claim it halfway.
    """
    from psycopg2 import Error as PostgresError
    from psycopg2 import sql

    if stale_databases:
        with _cursor() as cursor:
            for database in stale_databases:
                port = _session_port(database.name)
                with ExitStack() as stack:
                    if port is not None and not stack.enter_context(_port_claim(port)):
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
                        click.echo(f"Could not drop database {database.name}: {e}")
                    else:
                        click.echo(f"Dropped database {database.name}.")
    for folder in stale_folders:
        try:
            shutil.rmtree(folder)
        except OSError as e:
            click.echo(f"Could not remove Redis folder {folder}: {e}")
        else:
            click.echo(f"Removed Redis folder {folder}.")


def _find_leftovers(include_debug_data):
    """Return what ``--clean`` would remove now, skipping claimed session ports."""
    in_use = {_database_name(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))}
    stale_databases, stale_folders = leftovers(
        find_sessions(),
        find_redis_servers(),
        find_databases(),
        find_redis_folders(),
        include_debug_data=include_debug_data,
        in_use=in_use,
    )
    stale_databases = [
        d
        for d in stale_databases
        if _session_port(d.name) is None or not _port_is_claimed(_session_port(d.name))
    ]
    return stale_databases, stale_folders


def list_services(*, clean_leftovers, assume_yes, include_debug_data=False):
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
    stale_databases, stale_folders = _find_leftovers(include_debug_data)
    if not (stale_databases or stale_folders):
        click.echo("\nNo leftovers of ended test or debug sessions to clean.")
        return
    click.echo("\nLeftovers of ended test and debug sessions:")
    for d in stale_databases:
        click.echo(f"  database {d.name}")
    for folder in stale_folders:
        click.echo(f"  Redis folder {folder}")
    if not assume_yes and not sys.stdin.isatty():
        raise click.ClickException(
            "Nobody can confirm the removal here; pass --yes to remove them."
        )
    if not (assume_yes or click.confirm("Remove them?", default=False)):
        return
    # Sessions may have started while the question was open.
    now_databases, now_folders = _find_leftovers(include_debug_data)
    now_names = {d.name for d in now_databases}
    _clean(
        [d for d in stale_databases if d.name in now_names],
        [f for f in stale_folders if f in now_folders],
    )
