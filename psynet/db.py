import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import dallinger.db
import psycopg2
import psycopg2.extensions
from sqlalchemy import event, text

logger = logging.getLogger(__name__)

TRANSIENT_TRANSACTION_PGCODES = {"40001", "40P01", "55P03"}

_OTHER_DATABASE_CLIENTS_WHERE = (
    "datname = current_database() AND pid <> pg_backend_pid() "
    "AND usename = current_user"
)
OTHER_DATABASE_CLIENTS_SQL = text(
    "SELECT pid, usename, application_name, state FROM pg_stat_activity "
    f"WHERE {_OTHER_DATABASE_CLIENTS_WHERE}"
)
TERMINATE_OTHER_DATABASE_CLIENTS_SQL = text(
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    f"WHERE {_OTHER_DATABASE_CLIENTS_WHERE}"
)


def _gevent_wait_callback(conn, timeout=None):
    """Wait for psycopg2 I/O by yielding to other greenlets."""
    from gevent.socket import wait_read, wait_write

    while True:
        state = conn.poll()
        if state == psycopg2.extensions.POLL_OK:
            return
        if state == psycopg2.extensions.POLL_READ:
            wait_read(conn.fileno(), timeout=timeout)
        elif state == psycopg2.extensions.POLL_WRITE:
            wait_write(conn.fileno(), timeout=timeout)
        else:
            raise psycopg2.OperationalError(f"Bad psycopg2 poll state: {state!r}")


_blocking_psycopg_lock = threading.Lock()
_blocking_psycopg_depth = 0
_suspended_wait_callback = None


def _session_is_greenlet_local():
    """Return whether each greenlet gets its own scoped ORM session."""
    registry = getattr(dallinger.db.session.registry, "registry", None)
    return type(registry).__module__.startswith("gevent")


_warned_shared_session = False


def install_gevent_wait_callback():
    """Make psycopg2 cooperative in a gevent-patched process.

    Dallinger's web server, dev server, and RQ worker are gevent processes,
    but psycopg2 blocks the whole process while it waits on PostgreSQL. One
    request waiting on a lock then freezes every other request in that
    process, including the one holding the lock, until ``lock_timeout``. The
    wait callback lets other greenlets run while a query waits.

    Runs automatically on import and whenever the engine opens a connection,
    so gunicorn workers, the dev server, and the RQ worker are all covered.
    Does nothing outside gevent-patched processes, inside
    :func:`blocking_psycopg`, or if a callback is already installed. It also
    refuses, with a warning, when Dallinger was imported before patching:
    greenlets would then share one session and connection, and yielding
    mid-query would deadlock. Returns whether this call installed the
    callback.
    """
    global _warned_shared_session
    try:
        from gevent import monkey
    except ImportError:
        return False
    if not monkey.is_module_patched("socket"):
        return False
    with _blocking_psycopg_lock:
        if _blocking_psycopg_depth > 0:
            return False
        if psycopg2.extensions.get_wait_callback() is not None:
            return False
        if not _session_is_greenlet_local():
            if not _warned_shared_session:
                _warned_shared_session = True
                logger.warning(
                    "Not making psycopg2 cooperative: dallinger.db was imported "
                    "before gevent monkey-patching, so greenlets share one "
                    "database session."
                )
            return False
        psycopg2.extensions.set_wait_callback(_gevent_wait_callback)
    return True


@event.listens_for(dallinger.db.engine, "connect")
def _install_gevent_wait_callback_on_connect(dbapi_connection, connection_record):
    install_gevent_wait_callback()


# Also covers pooled connections opened before this module was imported,
# since the callback is process-wide.
install_gevent_wait_callback()


@contextmanager
def blocking_psycopg():
    """Suspend the psycopg2 wait callback, e.g. around ``copy_expert``.

    Experiment code must wrap any PostgreSQL ``COPY`` in this context manager,
    because psycopg2 rejects ``COPY`` while the callback is installed. The
    callback is process-wide, so overlapping suspensions from different
    greenlets or threads are counted and the callback returns only when the
    last one exits. Keep the block short: it blocks every greenlet in the
    process, and other queries in the process run without the callback.
    """
    global _blocking_psycopg_depth, _suspended_wait_callback
    with _blocking_psycopg_lock:
        if _blocking_psycopg_depth == 0:
            _suspended_wait_callback = psycopg2.extensions.get_wait_callback()
            psycopg2.extensions.set_wait_callback(None)
        _blocking_psycopg_depth += 1
    try:
        yield
    finally:
        with _blocking_psycopg_lock:
            _blocking_psycopg_depth -= 1
            if _blocking_psycopg_depth == 0:
                psycopg2.extensions.set_wait_callback(_suspended_wait_callback)
                _suspended_wait_callback = None


def is_transient_transaction_error(error):
    """Return whether a database error is lock timeout, deadlock, or serialization failure."""
    return (
        getattr(getattr(error, "orig", None), "pgcode", None)
        in TRANSIENT_TRANSACTION_PGCODES
    )


def release_local_database_connections():
    """Close this process's ORM sessions and dispose its connection pool."""
    from sqlalchemy.orm.session import close_all_sessions

    close_all_sessions()
    dallinger.db.engine.dispose()


def list_other_database_clients(*, release_local=True):
    """Return other same-role backends connected to this database.

    Parameters
    ----------
    release_local : bool
        If True (default), close this process's pooled connections first so
        they are not counted as another client. This disposes the SQLAlchemy
        engine pool and should only be used from destructive load/reset paths.
    """
    if release_local:
        release_local_database_connections()
    with dallinger.db.engine.connect() as con:
        return list(con.execute(OTHER_DATABASE_CLIENTS_SQL))


_transaction_depth = ContextVar("psynet_transaction_depth", default=0)
_read_only_render_depth = ContextVar("psynet_read_only_render_depth", default=0)


def _meaningfully_dirty(session):
    return [
        obj
        for obj in session.dirty
        if session.is_modified(obj, include_collections=True)
    ]


@event.listens_for(dallinger.db.session, "before_commit")
def _prevent_render_commit(session):
    if _read_only_render_depth.get() > 0:
        raise RuntimeError("Timeline rendering cannot commit database transactions.")


@event.listens_for(dallinger.db.session, "before_flush")
def _prevent_render_flush(session, flush_context, instances):
    if _read_only_render_depth.get() > 0 and (
        session.new or _meaningfully_dirty(session) or session.deleted
    ):
        raise RuntimeError("Timeline rendering cannot flush ORM mutations.")


@contextmanager
def transaction(commit: bool = True):
    """
    Context manager to handle database transactions.

    The crucial behaviour here is that ``session.remove()`` is called internally
    once the *outermost* context is exited, which ensures that the database session
    is closed. Nested ``transaction()`` calls reuse the existing session to avoid
    prematurely detaching ORM objects, while still preventing unintended long-lived
    sessions that can lead to performance issues including deadlocks.

    As opposed to ``dallinger.db.session_scope``, we by default commit the transaction
    at the end of the context. In general we want to discourage users from calling ``session.commit()``
    themselves, and just use this context manager to handle transactions automatically.
    This should be best for atomicity and performance.
    """
    depth = _transaction_depth.get()
    token = _transaction_depth.set(depth + 1)
    try:
        if depth == 0:
            with dallinger.db.sessions_scope(dallinger.db.session):
                yield
                if commit:
                    dallinger.db.session.commit()
        else:
            yield
            if commit:
                dallinger.db.session.commit()
    finally:
        _transaction_depth.reset(token)


def with_transaction(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with transaction():
            return func(*args, **kwargs)

    return wrapper


def _set_transaction_lock_timeout(seconds, session=None):
    """Bound PostgreSQL lock waits in the current transaction."""
    if session is None:
        session = dallinger.db.session
    session.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": f"{seconds}s"},
    )


@contextmanager
def read_only_transaction():
    """Run rendering in a fresh read-only transaction on the scoped session."""
    session = dallinger.db.session()
    if session.in_transaction():
        raise RuntimeError("Read-only rendering requires a committed write phase.")

    previous_autoflush = session.autoflush
    token = _read_only_render_depth.set(_read_only_render_depth.get() + 1)
    session.autoflush = False
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
        pending = {
            "new": [type(obj).__name__ for obj in session.new],
            "dirty": [type(obj).__name__ for obj in _meaningfully_dirty(session)],
            "deleted": [type(obj).__name__ for obj in session.deleted],
        }
        if any(pending.values()):
            raise RuntimeError(
                f"Timeline rendering attempted to mutate ORM state: {pending}."
            )
    finally:
        session.rollback()
        session.autoflush = previous_autoflush
        _read_only_render_depth.reset(token)
