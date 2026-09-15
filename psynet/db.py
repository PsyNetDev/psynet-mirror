from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import dallinger.db
from sqlalchemy import event, text

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
        they are not counted as another client.
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
