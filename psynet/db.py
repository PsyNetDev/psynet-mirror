from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import dallinger.db

_transaction_depth = ContextVar("psynet_transaction_depth", default=0)


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
