"""Idempotent PsyNet runtime initialisation.

This module isolates the heavy side effects that the original ``psynet/__init__.py``
performed at import time (dominate event-loop patch, Dallinger config patch,
gevent environment variable, debugpy import).  Putting them here allows the
minimal bootstrap package (``psynet`` without ``[experiment]``) to import
cleanly without pulling in dallinger or debugpy.

Usage
-----
Call :func:`ensure_runtime` exactly once before any experiment-runtime code
runs.  The full CLI path in ``psynet.command_line`` calls it at the top of
module import so every heavy command automatically gets it.  The bootstrap
CLI in ``psynet.bootstrap_cli`` does **not** call it, which keeps bootstrap
commands import-free.

The function is idempotent: repeated calls are no-ops.
"""

from __future__ import annotations

_runtime_initialized = False


def ensure_runtime() -> None:
    """Initialise PsyNet's heavy runtime dependencies (idempotent).

    Performs the following side effects on the first call:

    - Applies the dominate event-loop patch (requires dominate >= 2.9.1 fix).
    - Patches ``dallinger.config.Configuration.load`` to register PsyNet's
      extra config keys when no experiment is on the path.
    - Sets ``GEVENT_SUPPORT=True`` in the process environment.
    - Patches yaspin's Jupyter detection.
    - Imports ``psynet.recruiters`` (registers recruiter classes).

    Subsequent calls are no-ops.
    """
    global _runtime_initialized
    if _runtime_initialized:
        return
    _initialize_runtime()
    _runtime_initialized = True


def _initialize_runtime() -> None:
    """Apply heavy runtime imports and patches."""

    import asyncio
    import warnings

    import dominate
    from dallinger.config import ConfigSource, Configuration, experiment_available

    import psynet.recruiters  # noqa: F401
    from psynet.utils import (
        loading_experiment_classes,
        patch_yaspin_jupyter_detection,
    )

    # Fix event loop deprecation warning from dominate.
    dominate.dom_tag.get_event_loop = asyncio.get_running_loop

    warnings.filterwarnings(
        "ignore",
        message="This process.*is multi-threaded, use of fork.*may lead to deadlocks in the child",
        category=DeprecationWarning,
    )

    # Patch dallinger config to register PsyNet's extra parameters when no
    # experiment is available on the import path.
    old_load = Configuration.load

    def load(self, strict=True):
        if not experiment_available():
            from psynet.experiment import Experiment

            try:
                Experiment.extra_parameters()
            except KeyError as e:
                if "is already registered" in str(e):
                    pass
                else:
                    raise
            self.extend(
                Experiment.config_defaults(),
                strict=strict,
                source=ConfigSource.EXPERIMENT_DEFAULTS,
            )

        # Dallinger's loader imports experiment.py to read its extra
        # parameters, which redeclares the experiment's mapped classes.
        with loading_experiment_classes():
            old_load(self, strict=strict)

    Configuration.load = load

    import os

    os.environ["GEVENT_SUPPORT"] = "True"

    patch_yaspin_jupyter_detection()
