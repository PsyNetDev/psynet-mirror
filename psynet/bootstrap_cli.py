"""Minimal bootstrap CLI for PsyNet.

This module provides the ``psynet`` entry point.  It is intentionally slim so
that running ``psynet setup``, ``psynet scripts …``, ``psynet services …``,
and ``psynet generate-constraints`` works with only the minimal ``psynet``
distribution (i.e. without the ``[experiment]`` extra installed).

Dispatch strategy
-----------------
The ``main()`` function inspects ``sys.argv`` to decide which CLI to run:

- If the first user-visible argument is one of the *bootstrap commands*
  (``setup``, ``scripts``, ``services``, ``generate-constraints``), or the
  entire argument list is exactly a version flag (``psynet --version`` /
  ``psynet -V``), the lightweight bootstrap group is invoked directly without
  importing experiment-runtime code.

- Otherwise (or for bare ``psynet`` / ``psynet --help``) the full heavy CLI
  in ``psynet.command_line`` is imported and invoked.  If that import fails
  because a runtime module is missing, a friendly message names that module
  and directs the user to run ``psynet setup`` or install
  ``psynet[experiment]``. Other import defects propagate unchanged.

This pattern means that bootstrap commands are always fast and never require
the experiment runtime, while full-featured experiment commands are still
available whenever the runtime is installed.
"""

from __future__ import annotations

import sys

import click

from psynet.bootstrap_commands import register_bootstrap_commands
from psynet.version import psynet_version

_BOOTSTRAP_COMMANDS = frozenset(
    {
        "setup",
        "scripts",
        "services",
        "generate-constraints",
    }
)


# ---------------------------------------------------------------------------
# Bootstrap Click group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(
    psynet_version,
    "--version",
    "-V",
    message="%(version)s",
)
def _bootstrap():
    """PsyNet bootstrap commands (available without experiment runtime)."""
    pass


register_bootstrap_commands(_bootstrap)


# ---------------------------------------------------------------------------
# Entry point dispatcher
# ---------------------------------------------------------------------------


def _first_user_arg() -> str | None:
    """Return the first non-flag argument from sys.argv (after the script name)."""
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            return arg
    return None


def _has_version_flag() -> bool:
    """Return True only for bare ``psynet --version`` / ``psynet -V``.

    Nested uses such as ``psynet debug -V`` must reach the full CLI instead of
    being hijacked by the bootstrap group (which has no ``debug`` command).
    """
    return sys.argv[1:] in (["--version"], ["-V"])


def _load_full_psynet_cli():
    """Import the full experiment CLI group (requires ``[experiment]``)."""
    from psynet.command_line import psynet as _full_psynet

    return _full_psynet


def main() -> None:
    """Dispatcher: run bootstrap CLI or full experiment CLI.

    Bootstrap commands (``setup``, ``scripts``, ``services``,
    ``generate-constraints``) and bare version invocations (``psynet
    --version`` / ``psynet -V``) are handled without importing the experiment
    runtime.  Every other invocation delegates to the full
    ``psynet.command_line.psynet`` group, printing a helpful message if the
    ``[experiment]`` extra is not installed.
    """
    first = _first_user_arg()
    use_bootstrap = first in _BOOTSTRAP_COMMANDS or _has_version_flag()

    if use_bootstrap:
        _bootstrap(standalone_mode=True)
        return

    # Try loading the full experiment CLI.
    try:
        _full_psynet = _load_full_psynet_cli()
    except ModuleNotFoundError as exc:
        # A dependency of the experiment runtime is not installed. Include the
        # exact module name rather than masking every ImportError as this case.
        missing_module = exc.name or str(exc)
        if first is None or first in ("--help", "-h"):
            # Show bootstrap help, note that more commands need [experiment].
            click.echo(
                "PsyNet bootstrap CLI "
                f"(full runtime module {missing_module!r} is unavailable).\n\n"
                "Available commands: setup, scripts, services, generate-constraints\n\n"
                "To access full experiment commands:\n"
                "  psynet setup          (installs psynet[experiment] via constraints)\n"
                "  uv pip install 'psynet[experiment]'\n"
            )
            _bootstrap(["--help"], standalone_mode=False)
        else:
            click.echo(
                f"Error: command '{first}' requires the full PsyNet experiment "
                f"runtime, but module {missing_module!r} is unavailable.\n\n"
                "Install it with:\n"
                "  psynet setup\n"
                "or:\n"
                "  uv pip install 'psynet[experiment]'\n",
                err=True,
            )
            raise SystemExit(1) from exc
        return

    _full_psynet(standalone_mode=True)
