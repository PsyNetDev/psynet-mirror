"""Inter-process locks for experiment directories used by tests.

Testing an experiment scaffolds boilerplate files into its directory and
removes them again afterwards, writes ``.deploy/deployment_info.json``, and
links ``static/`` into local asset storage. Two processes doing this in the
same directory at the same time delete each other's files, so test sessions
that may run in parallel (CI slots, or several coding agents on one machine)
hold an exclusive lock on the directory for as long as they use it.

A parent process that already holds the lock (for example the CI runner,
which scaffolds a demo before starting pytest on it) passes it down by setting
:data:`HELD_LOCK_ENV_VAR` to the directory, so the child does not deadlock.
"""

import fcntl
import hashlib
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

HELD_LOCK_ENV_VAR = "PSYNET_HELD_EXPERIMENT_DIRECTORY_LOCK"


def _lock_path(directory):
    key = hashlib.sha1(str(directory).encode()).hexdigest()[:16]
    lock_dir = Path(tempfile.gettempdir()) / "psynet-experiment-locks"
    lock_dir.mkdir(exist_ok=True)
    return lock_dir / f"{key}.lock"


@contextmanager
def experiment_directory_lock(directory, export=True):
    """Hold an exclusive lock on ``directory`` while the block runs.

    Waits for other processes that hold the same lock, logging how long the
    wait took. With ``export=True``, sets :data:`HELD_LOCK_ENV_VAR` in
    ``os.environ`` so child processes inherit the lock; multithreaded callers
    should pass ``export=False`` and set the variable in each child's
    environment instead.
    """
    directory = os.path.realpath(directory)
    if os.environ.get(HELD_LOCK_ENV_VAR) == directory:
        yield
        return

    with open(_lock_path(directory), "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("Waiting for another test process to release %s...", directory)
            start = time.monotonic()
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            logger.info(
                "Acquired %s after waiting %.1f s.", directory, time.monotonic() - start
            )
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
