"""Early pytest plugin that runs the session in an isolated local environment.

Load it with ``-p psynet.pytest_environment`` so that it is imported before
Dallinger connects to PostgreSQL and Redis; see
:mod:`psynet.isolated_environment`.
"""

import atexit
import os
import sys

import pytest

from .isolated_environment import ENV_VAR, SHARED, IsolatedEnvironment, should_isolate

_INFO_ONLY_ARGS = {"-h", "--help", "-V", "--version"}


def _start():
    if not should_isolate() or _INFO_ONLY_ARGS.intersection(sys.argv[1:]):
        return None
    if "dallinger.db" in sys.modules:
        raise pytest.UsageError(
            "Dallinger connected to the local database before PsyNet could give "
            "these tests their own, so they would reset any local debug server. "
            f"Load this plugin earlier, or set {ENV_VAR}={SHARED} to share the "
            "local database and Redis."
        )
    try:
        environment = IsolatedEnvironment.start()
    except Exception as e:
        raise pytest.UsageError(
            f"Could not give these tests their own database and Redis ({e}). "
            f"Set {ENV_VAR}={SHARED} to run them against the local database and "
            "Redis instead, which resets any local debug server."
        ) from e
    atexit.register(environment.close)
    os.environ.update(environment.env)
    print(environment.describe(), file=sys.stderr)
    return environment


_environment = _start()


def pytest_unconfigure(config):
    if _environment is not None:
        _environment.close()
