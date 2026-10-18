"""Minimal bootstrap CLI for PsyNet.

This module provides the ``psynet`` entry point.  It is intentionally slim so
that running ``psynet setup``, ``psynet scripts …``, ``psynet services …``,
``psynet generate-constraints`` and ``psynet docs …`` works with only the minimal ``psynet``
distribution (i.e. without the ``[experiment]`` extra installed).

Dispatch strategy
-----------------
The ``main()`` function inspects ``sys.argv`` to decide which CLI to run:

- If the first user-visible argument is one of the *bootstrap commands*
  (``setup``, ``scripts``, ``services``, ``generate-constraints``, ``docs``), or the
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

import os
import sys
import traceback
from pathlib import Path

import click

from psynet.bootstrap_commands import register_bootstrap_commands
from psynet.version import psynet_version

_BOOTSTRAP_COMMANDS = frozenset(
    {
        "setup",
        "scripts",
        "services",
        "generate-constraints",
        "docs",
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


def _is_author_file(filename: str | None, experiment_dir: Path) -> bool:
    """Return True if ``filename`` is a source file in the experiment folder.

    Files in a virtual environment inside the experiment folder don't count.
    """
    if not filename or filename.startswith("<"):
        return False
    path = Path(filename).resolve()
    return (
        path.is_file()
        and path.is_relative_to(experiment_dir)
        and not path.is_relative_to(Path(sys.prefix).resolve())
        and "site-packages" not in path.parts
    )


def _exception_chain_lines(exc: BaseException) -> list[str]:
    """Format the one-line summaries of ``exc`` and the exceptions it chains to."""
    chain = []
    current = traceback.TracebackException.from_exception(exc)
    while current is not None:
        chain.append(current)
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None

    chain.reverse()
    lines = list(chain[0].format_exception_only())
    for older, newer in zip(chain, chain[1:]):
        if newer.__cause__ is older:
            lines.append(
                "\nThe above exception was the direct cause of the following exception:\n\n"
            )
        else:
            lines.append(
                "\nDuring handling of the above exception, another exception occurred:\n\n"
            )
        lines.extend(newer.format_exception_only())
    return lines


def _experiment_import_error_message(
    exc: BaseException, experiment_dir: Path
) -> str | None:
    """Summarise an error raised while importing the experiment's own code.

    The summary keeps the frames from the experiment folder plus the frame
    that raised the error. Returns None if ``exc`` didn't come from importing
    a module in ``experiment_dir``.
    """
    if not (experiment_dir / "experiment.py").is_file() or isinstance(
        exc, BaseExceptionGroup
    ):
        return None

    frames = traceback.extract_tb(exc.__traceback__)
    author_frames = [f for f in frames if _is_author_file(f.filename, experiment_dir)]
    if not any(f.name == "<module>" for f in author_frames):
        if not (
            isinstance(exc, SyntaxError)
            and _is_author_file(exc.filename, experiment_dir)
        ):
            return None

    if isinstance(exc, SyntaxError) and exc.filename and exc.filename[0] != "<":
        culprit = Path(exc.filename).resolve()
    else:
        culprit = Path(author_frames[-1].filename).resolve()
        if frames[-1] is not author_frames[-1]:
            author_frames.append(frames[-1])

    if culprit.is_relative_to(experiment_dir):
        culprit = culprit.relative_to(experiment_dir)
    details = "".join(
        traceback.format_list(author_frames) + _exception_chain_lines(exc)
    )
    return (
        f"Error: Couldn't load the experiment because of an error in "
        f"{culprit}:\n\n{details}\n"
        "Fix the error and run the command again. "
        "To see the full traceback, set PSYNET_SHOW_TRACEBACK=1."
    )


def _run_full_cli(full_psynet) -> None:
    """Run the full CLI, shortening tracebacks from the experiment's own code."""
    try:
        full_psynet(standalone_mode=True)
    except Exception as exc:
        show_traceback = os.environ.get("PSYNET_SHOW_TRACEBACK", "")
        if show_traceback.lower() not in ("", "0", "false", "no"):
            raise
        message = _experiment_import_error_message(exc, Path.cwd().resolve())
        if message is None:
            raise
        click.echo(message, err=True)
        raise SystemExit(1) from exc


def main() -> None:
    """Dispatcher: run bootstrap CLI or full experiment CLI.

    Bootstrap commands (``setup``, ``scripts``, ``services``,
    ``generate-constraints``, ``docs``) and bare version invocations (``psynet
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
                "Available commands: setup, scripts, services, generate-constraints, docs\n\n"
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

    _run_full_cli(_full_psynet)
