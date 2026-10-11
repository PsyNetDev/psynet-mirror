"""Deprecated: async processes are now async jobs in :mod:`psynet.async_job`."""

import warnings

from .async_job import AsyncJob, LocalAsyncJob, WorkerAsyncJob


def WorkerAsyncProcess(*args, **kwargs):
    """Deprecated: create a :class:`~psynet.async_job.WorkerAsyncJob` and enqueue it."""
    warnings.warn(
        "WorkerAsyncProcess(...) is deprecated; use "
        "psynet.async_job.WorkerAsyncJob(...).enqueue() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return WorkerAsyncJob(*args, **kwargs).enqueue()


def LocalAsyncProcess(*args, **kwargs):
    """Deprecated: create a :class:`~psynet.async_job.LocalAsyncJob` and enqueue it."""
    warnings.warn(
        "LocalAsyncProcess(...) is deprecated; use "
        "psynet.async_job.LocalAsyncJob(...).enqueue() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return LocalAsyncJob(*args, **kwargs).enqueue()


def __getattr__(name):
    if name == "AsyncProcess":
        warnings.warn(
            "psynet.process.AsyncProcess has been renamed to psynet.async_job.AsyncJob.",
            DeprecationWarning,
            stacklevel=2,
        )
        return AsyncJob
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
