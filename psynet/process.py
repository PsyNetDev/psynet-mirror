"""Deprecated: async processes are now async jobs in :mod:`psynet.async_job`."""

import warnings

from .async_job import AsyncJob, LocalAsyncJob, WorkerAsyncJob


class _DeprecatedJobAlias:
    """Warning stand-in for a renamed job class.

    Calling it creates and enqueues the new job; public attribute access,
    ``isinstance`` and ``issubclass`` are forwarded to the new class, and
    subclassing it subclasses the new class. It is not a mapped class
    itself, so it adds no SQLAlchemy polymorphic identity.
    """

    def __init__(self, old_name, target):
        self._old_name = old_name
        self._target = target

    def _warn(self, usage=""):
        warnings.warn(
            f"psynet.process.{self._old_name} is deprecated; use "
            f"psynet.async_job.{self._target.__name__}{usage} instead.",
            DeprecationWarning,
            stacklevel=3,
        )

    def __call__(self, *args, **kwargs):
        self._warn("(...).enqueue()")
        return self._target(*args, **kwargs).enqueue()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self._warn()
        return getattr(self._target, name)

    def __instancecheck__(self, obj):
        self._warn()
        return isinstance(obj, self._target)

    def __subclasscheck__(self, cls):
        self._warn()
        return issubclass(cls, self._target)

    def __mro_entries__(self, bases):
        self._warn(" (and call .enqueue() on each job)")
        return (self._target,)

    def __repr__(self):
        return f"<deprecated alias {self._old_name} of {self._target.__name__}>"


WorkerAsyncProcess = _DeprecatedJobAlias("WorkerAsyncProcess", WorkerAsyncJob)
LocalAsyncProcess = _DeprecatedJobAlias("LocalAsyncProcess", LocalAsyncJob)


def __getattr__(name):
    if name == "AsyncProcess":
        warnings.warn(
            "psynet.process.AsyncProcess has been renamed to psynet.async_job.AsyncJob.",
            DeprecationWarning,
            stacklevel=2,
        )
        return AsyncJob
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
