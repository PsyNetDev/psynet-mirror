"""Early pytest plugin that runs the session in an isolated local environment.

Load it with ``-p psynet.pytest_environment`` so that it is imported before
Dallinger connects to PostgreSQL and Redis; see
:mod:`psynet.isolated_environment`.
"""

import atexit
import os
import sys

from .isolated_environment import IsolatedEnvironment, should_isolate


def _start():
    if not should_isolate():
        return None
    if "dallinger.db" in sys.modules:
        print(
            "Dallinger is already connected to the shared database, so these tests "
            "share it with any local debug server.",
            file=sys.stderr,
        )
        return None
    try:
        environment = IsolatedEnvironment.start()
    except Exception as e:
        print(
            f"Could not isolate these tests from local debug servers ({e}); "
            "they will share the local database and Redis.",
            file=sys.stderr,
        )
        return None
    atexit.register(environment.close)
    os.environ.update(environment.env)
    print(environment.describe(), file=sys.stderr)
    return environment


_environment = _start()


def pytest_unconfigure(config):
    if _environment is not None:
        _environment.close()
