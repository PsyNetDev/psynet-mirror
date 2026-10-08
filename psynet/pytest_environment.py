"""Early pytest plugin that runs the session in an isolated local environment.

Load it with ``-p psynet.pytest_environment`` so that it is imported before
Dallinger connects to PostgreSQL and Redis; see
:mod:`psynet.isolated_environment`.
"""

import atexit
import os
import sys

import pytest

from .isolated_environment import (
    READY_ENV_VAR,
    IsolatedEnvironment,
    IsolationError,
    check_no_debug_server,
    shared_environment_warning,
    should_isolate,
)

# Runs that don't execute tests and so don't need their own services.
_INFO_ONLY_ARGS = {"-h", "--help", "-V", "--version"}
_INFO_ONLY_ARGS |= {
    "--co",
    "--collect-only",
    "--collectonly",
    "--fixtures",
    "--markers",
}


def _start():
    if _INFO_ONLY_ARGS.intersection(sys.argv[1:]):
        return
    try:
        isolate = should_isolate()
    except ValueError as e:
        raise pytest.UsageError(str(e)) from e
    if not isolate:
        warning = shared_environment_warning()
        if warning:
            print(warning, file=sys.stderr)
            os.environ[READY_ENV_VAR] = "1"
        return
    if "dallinger.db" in sys.modules:
        raise pytest.UsageError(
            str(
                IsolationError(
                    "Dallinger connected to the local database first; load "
                    "this plugin earlier"
                )
            )
        )
    try:
        check_no_debug_server(os.getcwd())
        environment = IsolatedEnvironment.start()
    except RuntimeError as e:
        raise pytest.UsageError(str(e)) from e
    # Not pytest_unconfigure: a nested pytest.main() in the same process
    # would close the outer session's environment.
    atexit.register(environment.close)
    os.environ.update(environment.env)
    print(environment.describe(), file=sys.stderr)


_start()
