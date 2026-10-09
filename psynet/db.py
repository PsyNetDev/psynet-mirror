"""Database sessions, transactions and who may commit them.

PsyNet runs each unit of work (an HTTP request, a scheduled task, a worker
job, a CLI command, a deploy step) in one transaction that the code starting
that unit commits. That code is the transaction's owner: route decorators
such as ``with_transaction``, :func:`transaction`, scheduled-task wrappers,
worker entry points and CLI commands. Everything they call, framework helpers
included, leaves committing to the owner, and uses ``db.session.flush()`` when
it needs database-generated values. Timeline steps enforce this with
:func:`forbid_commits`.

A helper may commit early to keep local records consistent with an external
call that cannot be undone or should not be repeated, such as a payment, a
panel provider's API or a rate-limited request. It must do so through
:func:`_commit_external_call_state`, which keeps the exceptions easy to find
and refuses to run inside timeline steps, whose work the commit would save
half-finished, inside savepoints and during rendering; such calls belong in
an ``AsyncCodeBlock``. The other exceptions are ``Experiment.handle_error``,
which rolls back the failed work and commits the error record in its place,
and recruiter hooks that some Dallinger callers (the clock, ``/participant``
and ``/load-participant``) run without committing.
``tests/isolated/test_commit_sites.py`` lists every function in the package
that calls ``.commit()`` directly, with its reason; adding one means adding it
there.
"""

import copy
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
    last one exits. Keep the block short: while it is active, every query in
    the process, from any greenlet, blocks the whole process until it returns.
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


def _in_read_only_render():
    """True inside :func:`read_only_transaction`, where ORM writes raise."""
    return _read_only_render_depth.get() > 0


def _meaningfully_dirty(session):
    return [
        obj
        for obj in session.dirty
        if session.is_modified(obj, include_collections=True)
    ]


class _CommitGuard:
    """The innermost :func:`forbid_commits` block and the transaction it protects."""

    def __init__(self, operation, root, parent, savepoint):
        self.operation = operation
        self.root = root
        self.parent = parent
        self.savepoint = savepoint

    def savepoint_closed(self):
        """Return whether guarded code ended the savepoint the guard started in."""
        return self.savepoint is not None and not self.savepoint.is_active


_commit_forbidden_in = ContextVar("psynet_commit_forbidden_in", default=None)


@event.listens_for(dallinger.db.session, "before_commit")
def _prevent_render_commit(session):
    if _read_only_render_depth.get() > 0:
        raise RuntimeError("Timeline rendering cannot commit database transactions.")
    guard = _commit_forbidden_in.get()
    # Only savepoints opened inside the guarded code may be released; in
    # SQLAlchemy 1.4's legacy mode, commit() inside an enclosing savepoint
    # would release that one instead, and after a rollback() of that
    # savepoint it would commit the outer transaction.
    if guard is not None and (
        session.get_nested_transaction() is guard.savepoint or guard.savepoint_closed()
    ):
        raise RuntimeError(_forbidden_commit_message(guard.operation, "commit"))


_SAVING_CHANGES_DOCS_PAGE = "code/project/classes_and_sqlalchemy"


def _forbidden_commit_message(operation, action):
    from psynet import __version__
    from psynet.local_docs import published_docs_url

    docs_url = (
        f"{published_docs_url(__version__)}{_SAVING_CHANGES_DOCS_PAGE}.html"
        "#saving-changes"
    )
    return (
        f"{operation} called db.session.{action}(). PsyNet runs this code inside "
        "a database transaction that it commits itself once the step has "
        "finished. Committing or rolling back early releases the participant's "
        "lock and can save half-finished changes.\n"
        "Remove the call: PsyNet saves your changes automatically. If you need "
        "the ID of a new object straight away, call db.session.flush() instead.\n"
        f"See {docs_url} (or run: psynet docs show {_SAVING_CHANGES_DOCS_PAGE})."
    )


@contextmanager
def forbid_commits(operation: str):
    """Fail if code inside this block commits or rolls back the caller's transaction.

    PsyNet runs experiment code (timeline logic, response processing, trial
    maker hooks) inside a transaction that the framework commits. A commit
    inside that code releases the caller's row locks early and saves a partial
    unit of work. Savepoints (``begin_nested``) remain allowed. Guards nest;
    the innermost ``operation`` names the code in the error message.

    Parameters
    ----------
    operation :
        Description of the guarded code, used in the error message.
    """
    session = dallinger.db.session()
    guard = _CommitGuard(
        operation,
        session.get_transaction(),
        _commit_forbidden_in.get(),
        session.get_nested_transaction(),
    )
    token = _commit_forbidden_in.set(guard)
    try:
        yield
    finally:
        _commit_forbidden_in.reset(token)
    if guard.savepoint_closed() or (
        guard.root is not None and session.get_transaction() is not guard.root
    ):
        raise RuntimeError(_forbidden_commit_message(operation, "rollback"))


def _commit_external_call_state():
    """Commit now so local records match an external call that cannot be repeated.

    Use it just before an external call, so a crash after the call cannot
    lose the state the call reports, or just after it, so a later failure in
    the same unit of work cannot lose the record that the call happened. The
    commit saves the whole unit of work so far, so only code whose
    transaction's owner expects it may make such calls: routes, worker jobs
    (including ``AsyncCodeBlock``), scheduled tasks and CLI commands.

    It raises where :func:`_check_external_call_allowed` does; call that
    first when the commit comes after the call.
    """
    _check_external_call_allowed()
    dallinger.db.session.commit()


def _check_external_call_allowed():
    """Raise unless :func:`_commit_external_call_state` may commit here.

    Inside :func:`forbid_commits` the commit would save a timeline step's
    half-finished changes, and inside a savepoint ``commit()`` would only
    release the savepoint, so a later rollback would still lose the record.
    Call it before an external call whose result is committed afterwards, so
    the call is never made without its record. Payment and panel entry
    points call it first, so a misplaced call fails even when nothing would
    be sent.
    """
    if _in_read_only_render():
        raise RuntimeError(
            "Timeline rendering cannot make external calls; make them from an "
            "AsyncCodeBlock."
        )
    guard = _commit_forbidden_in.get()
    if guard is not None:
        raise RuntimeError(
            f"{guard.operation} tried to make an external call, such as a "
            "payment or a recruitment-platform request, that must commit the "
            "database. "
            "PsyNet commits this code's changes only once it has finished, so "
            "committing here would save half-finished changes.\n"
            "Make the call from an AsyncCodeBlock instead (or, outside the "
            "timeline, a WorkerAsyncProcess), which runs in its own "
            "transaction after this one commits."
        )
    if dallinger.db.session().in_nested_transaction():
        raise RuntimeError(
            "Payment and recruitment-platform calls cannot run inside a "
            "savepoint (db.session.begin_nested()); make the call outside it."
        )


_SAVEPOINT_SNAPSHOTS_KEY = "psynet_session_queue_savepoint_snapshots"
_session_queues = []


class _SessionQueue:
    """Per-session work queued during a transaction for use once it commits.

    A savepoint rollback restores the queue to what it held when the
    savepoint began, and a root rollback empties it. With ``on_commit``, the
    root commit takes the queue and passes it to ``on_commit``, which runs
    inside SQLAlchemy's ``after_commit`` event and so must not use the
    database; closing the session also empties such a queue. Without
    ``on_commit``, the queue survives the commit until the caller takes it.
    Each session has its own queue, so another session's commit or rollback
    cannot affect it.
    """

    def __init__(self, name, factory, on_commit=None):
        self.key = f"psynet_{name}"
        self.factory = factory
        self.on_commit = on_commit
        _session_queues.append(self)

    def get(self):
        """Return the current session's queue for adding to, creating it if needed.

        With ``on_commit``, begins a transaction if none is open, so the
        additions wait for a commit rather than for whichever transaction
        happens to come next.
        """
        session = dallinger.db.session()
        if self.on_commit is not None and session.get_transaction() is None:
            session.begin()
        value = session.info.get(self.key)
        if value is None:
            value = session.info[self.key] = self.factory()
        return value

    def peek(self):
        """Return a copy of the current session's queue, leaving it in place."""
        value = dallinger.db.session().info.get(self.key)
        return self.factory() if value is None else copy.copy(value)

    def take(self):
        """Remove and return the current session's queue."""
        value = dallinger.db.session().info.pop(self.key, None)
        return self.factory() if value is None else value

    def replace(self, value):
        """Set the current session's queue to ``value``."""
        info = dallinger.db.session().info
        if value:
            info[self.key] = value
        else:
            info.pop(self.key, None)


@event.listens_for(dallinger.db.session, "after_transaction_create")
def _snapshot_session_queues(session, transaction):
    if transaction.nested:
        snapshot = {
            queue.key: copy.copy(session.info[queue.key])
            for queue in _session_queues
            if queue.key in session.info
        }
        session.info.setdefault(_SAVEPOINT_SNAPSHOTS_KEY, []).append(snapshot)


@event.listens_for(dallinger.db.session, "after_commit")
def _hand_over_session_queues(session):
    # Releasing a savepoint also fires after_commit; wait for the root commit.
    if session.in_nested_transaction():
        return
    for queue in _session_queues:
        if queue.on_commit is None:
            continue
        value = session.info.pop(queue.key, None)
        if value:
            try:
                queue.on_commit(value)
            except Exception:
                logger.exception("Handling %s after the commit failed.", queue.key)


@event.listens_for(dallinger.db.session, "after_rollback")
def _restore_session_queues(session):
    """Restore the queues of a rolled-back savepoint, or empty them on a root rollback.

    Detect the savepoint via the snapshot stack, because
    ``in_nested_transaction()`` may already be false when this runs.
    """
    snapshots = session.info.get(_SAVEPOINT_SNAPSHOTS_KEY)
    restored = snapshots[-1] if snapshots else {}
    for queue in _session_queues:
        if queue.key in restored:
            session.info[queue.key] = copy.copy(restored[queue.key])
        else:
            session.info.pop(queue.key, None)


@event.listens_for(dallinger.db.session, "after_transaction_end")
def _end_session_queue_transaction(session, transaction):
    if transaction.nested:
        snapshots = session.info.get(_SAVEPOINT_SNAPSHOTS_KEY)
        if snapshots:
            snapshots.pop()
    elif transaction.parent is None:
        session.info.pop(_SAVEPOINT_SNAPSHOTS_KEY, None)
        # Session.close() ends the root transaction without after_rollback.
        for queue in _session_queues:
            if queue.on_commit is not None:
                session.info.pop(queue.key, None)


def _run_callbacks(callbacks):
    for callback in callbacks:
        try:
            callback()
        except Exception:
            logger.exception("After-commit callback %r failed.", callback)


_after_commit_callbacks = _SessionQueue(
    "after_commit_callbacks", list, on_commit=_run_callbacks
)


def _call_after_commit(callback):
    """Run ``callback`` once the current root transaction commits; drop it if it rolls back.

    For side effects, such as notifications and launching worker jobs, that
    should only happen once the transaction's changes are saved. Callbacks
    queued inside a savepoint are dropped if that savepoint rolls back.
    Callbacks run in the order they were queued, inside SQLAlchemy's
    ``after_commit`` event, so they must not use the database or queue
    further callbacks, which would be dropped. Each session
    has its own queue, so another session's commit cannot run them.
    """
    _after_commit_callbacks.get().append(callback)


@event.listens_for(dallinger.db.session, "after_transaction_create")
def _guard_transactions_begun_inside_forbid_commits(session, transaction):
    """Let guards with no transaction yet protect the next one the session begins.

    A guard has no root when it starts outside a transaction; without this,
    a later rollback would go unnoticed.
    """
    scoped = dallinger.db.session.registry
    if transaction.parent is not None or not scoped.has() or session is not scoped():
        return
    guard = _commit_forbidden_in.get()
    while guard is not None and guard.root is None:
        guard.root = transaction
        guard = guard.parent


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
