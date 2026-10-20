"""Inter-process locks for experiment directories used by tests and local servers.

Testing an experiment scaffolds boilerplate files into its directory and
removes them again afterwards, writes ``.deploy/deployment_info.json``, and
links ``static/`` into local asset storage; ``psynet debug local`` and
``psynet deploy local`` do the same while they serve it. Two processes doing
this in the same directory at the same time delete each other's files, so
each holds an exclusive lock on the directory for as long as it uses it.

Test sessions that may run in parallel (CI slots, or several coding agents on
one machine) wait for each other. A server holds the lock until it is
stopped, so waiting for one would hang: tests refuse to start instead, and so
does a server that finds the lock held. The holder writes its PID and kind
(:data:`TEST_SESSION` or :data:`SERVER`) into the lock file so that waiting
and refusal messages can say what holds it.

A parent process that already holds the lock (for example the CI runner,
which scaffolds a demo before starting pytest on it) passes it down by setting
:data:`HELD_LOCK_ENV_VAR` to the directory, so the child does not deadlock.
"""

import fcntl
import hashlib
import logging
import os
import time
from contextlib import contextmanager

from .. import isolated_environment

logger = logging.getLogger(__name__)

HELD_LOCK_ENV_VAR = "PSYNET_HELD_EXPERIMENT_DIRECTORY_LOCK"
TEST_SESSION = "test session"
SERVER = "server"


class DirectoryInUseError(RuntimeError):
    """Raised when a local server holds, or is refused, an experiment directory."""


def _lock_path(directory):
    key = hashlib.sha1(str(directory).encode()).hexdigest()[:16]
    return isolated_environment.lock_path(f"psynet-experiment-{key}")


def _holder(lock_file):
    """Return the ``(pid, kind)`` recorded in ``lock_file``; empty strings if unknown."""
    lock_file.seek(0)
    pid, _, kind = lock_file.read().strip().partition(" ")
    return pid, kind


#: How long to wait for a new holder to record itself, or for a probe to finish.
_HOLDER_TIMEOUT_S = 1.0


def _try_acquire(lock_file):
    """Take the lock without waiting for its holder; return None, or the holder.

    The holder records itself just after taking the lock, and a brief probe
    (:func:`check_no_server`) records nothing, so an unknown holder is
    retried briefly before it is returned as ``("", "")``.

    Returns
    -------
    tuple of str or None
        None if the lock is now held by ``lock_file``, otherwise the
        ``(pid, kind)`` recorded by the holder.
    """
    deadline = time.monotonic() + _HOLDER_TIMEOUT_S
    while True:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None
        except BlockingIOError:
            holder = _holder(lock_file)
            if holder[0] or time.monotonic() > deadline:
                return holder
            time.sleep(0.05)


def _describe(pid, kind):
    if not pid:
        return "another PsyNet process"
    return f"a PsyNet {kind or 'process'} (PID {pid})"


def _in_use_error(directory, pid, kind):
    holder = _describe(pid, kind)
    return DirectoryInUseError(
        f"{holder[0].upper()}{holder[1:]} is using {directory}, and this "
        "command would replace its generated files. Stop it, or run this "
        "command in a copy of the experiment such as a git worktree."
    )


@contextmanager
def experiment_directory_lock(directory, export=True, *, kind=TEST_SESSION):
    """Hold an exclusive lock on ``directory`` while the block runs.

    Parameters
    ----------
    directory : str or os.PathLike
        The experiment directory.
    export : bool
        Whether to set :data:`HELD_LOCK_ENV_VAR` in ``os.environ`` so that
        child processes inherit the lock; multithreaded callers should pass
        ``False`` and set the variable in each child's environment instead.
    kind : str
        :data:`TEST_SESSION` waits for other test sessions, logging how long
        the wait took. :data:`SERVER` never waits.

    Raises
    ------
    DirectoryInUseError
        If a server, or a holder that hasn't recorded itself (such as one
        whose lock file this user can't write), holds the lock, or ``kind`` is
        :data:`SERVER` and anything holds it.
    OSError
        If the lock file can't be opened.
    """
    directory = os.path.realpath(directory)
    if os.environ.get(HELD_LOCK_ENV_VAR) == directory:
        yield
        return

    with isolated_environment.open_lock_file(_lock_path(directory)) as lock_file:
        holder = _try_acquire(lock_file)
        if holder is not None:
            pid, held_by = holder
            # An unknown holder may be a server, which would never release it.
            if kind == SERVER or held_by != TEST_SESSION:
                raise _in_use_error(directory, pid, held_by)
            logger.info(
                "Waiting for %s to release %s...", _describe(pid, held_by), directory
            )
            start = time.monotonic()
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            logger.info(
                "Acquired %s after waiting %.1f s.", directory, time.monotonic() - start
            )
        if lock_file.writable():
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"{os.getpid()} {kind}")
            lock_file.flush()
        previous = os.environ.get(HELD_LOCK_ENV_VAR)
        if export:
            os.environ[HELD_LOCK_ENV_VAR] = directory
        try:
            yield
        finally:
            if export:
                if previous is None:
                    os.environ.pop(HELD_LOCK_ENV_VAR, None)
                else:
                    os.environ[HELD_LOCK_ENV_VAR] = previous
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def check_no_server(directory):
    """Raise :class:`DirectoryInUseError` if a local server holds ``directory``'s lock.

    Lets a test session fail before it creates its database and Redis; a
    test session that holds the lock is waited for later instead. Holders
    that don't record themselves are refused, as by
    :func:`experiment_directory_lock`.
    """
    directory = os.path.realpath(directory)
    if os.environ.get(HELD_LOCK_ENV_VAR) == directory:
        return
    with isolated_environment.open_lock_file(_lock_path(directory)) as lock_file:
        holder = _try_acquire(lock_file)
        if holder is not None and holder[1] != TEST_SESSION:
            raise _in_use_error(directory, *holder)
