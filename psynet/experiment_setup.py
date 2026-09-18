"""Prepare experiment directories and synchronize their virtual environments.

This module holds the non-Click orchestration used by ``psynet setup`` and
``psynet scripts scaffold``: virtualenv checks, shared-checkout sync gating,
editable PsyNet requirement selection, and scaffold/constraint preparation.
Click commands stay in ``command_line`` and call into these helpers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path

import click

from .experiment_scaffold import (
    commit_psynet_requirement,
    editable_psynet_requirement,
    get_editable_psynet_source,
    get_psynet_requirement,
    installed_psynet_direct_requirement,
    pin_unpinned_psynet_requirement,
    scaffold_experiment_directory,
    set_psynet_requirement,
)
from .light_utils import (
    ExperimentDirectoryNameError,
    ensure_experiment_directory_name_does_not_conflict,
    get_psynet_root,
    git_command_available,
    git_repository_available,
    is_in_repo_experiment,
)


class _GitStatus(str, Enum):
    """Outcome of ensuring an experiment has a usable Git repository."""

    READY = "ready"
    MISSING_GIT = "missing_git"
    INIT_FAILED = "init_failed"


def _git_repository_root():
    """Return the work-tree root of the containing repository, if any."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _containing_worktree_ignores_experiment():
    """Return whether the containing worktree ignores this experiment directory.

    Dallinger packages files via ``git ls-files``, so an experiment that its
    surrounding repository ignores would deploy with no files at all. A concrete
    tracked-intent file is checked when present, otherwise the directory itself.
    """
    target = "experiment.py" if Path("experiment.py").exists() else "."
    result = subprocess.run(
        ["git", "check-ignore", "-q", target],
        capture_output=True,
        text=True,
        check=False,
    )
    # 0 => ignored, 1 => not ignored, anything else => treat as not ignored.
    return result.returncode == 0


def _init_git_repository_here():
    """Run ``git init`` in the current directory and report the outcome."""
    result = subprocess.run(
        ["git", "init"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f"\n{detail}" if detail else ""
        click.echo(
            "Warning: could not initialise a Git repository here. Run "
            f"'git init' manually before debugging or deploying.{suffix}",
            err=True,
        )
        return _GitStatus.INIT_FAILED
    click.echo(f"Initialised a Git repository in {Path.cwd() / '.git'}.")
    return _GitStatus.READY


def _ensure_git_repository():
    """Ensure this experiment has a Git repository suitable for deployment.

    Dallinger packages an experiment by intersecting its directory tree with
    ``git ls-files``, so a repository is what gives deployment its ignore rules.
    Being anywhere inside a work tree is normally sufficient -- the experiment
    need not be the repository root -- so a surrounding repository (for example
    a monorepo of experiments, or a bundled experiment inside the PsyNet source
    checkout) is used as-is rather than nested inside a new one.

    The exception is a surrounding repository that *ignores* this experiment
    directory: there ``git ls-files`` returns nothing, so setup initialises a
    dedicated repository here instead of silently producing an empty deployment.
    """
    if git_repository_available():
        if not _containing_worktree_ignores_experiment():
            root = _git_repository_root()
            location = f" at {root}" if root else ""
            click.echo(f"Using the existing Git repository{location}.")
            return _GitStatus.READY
        click.echo(
            "The surrounding Git repository ignores this experiment directory, "
            "so setup is initialising a dedicated repository here (otherwise "
            "deployment would package no files)."
        )
        return _init_git_repository_here()

    if not git_command_available():
        click.echo(
            "Warning: Git does not appear to be installed, so no repository "
            "could be initialised here. Install Git from "
            "https://git-scm.com/downloads and run 'git init' in this "
            "directory before debugging or deploying.",
            err=True,
        )
        return _GitStatus.MISSING_GIT

    return _init_git_repository_here()


def _setup_was_delegated():
    """Return whether this run was launched by an outer ``psynet setup``.

    When delegated, the environment was created by that outer run, so the
    user's own shell is not using it yet and must activate it before running
    anything else. Otherwise Dallinger's ``.python-version`` check fails against
    whichever interpreter the shell still has active.
    """
    return bool(os.environ.get(_DELEGATED_SETUP_ENV_VAR))


def _echo_useful_commands(*, git_status, activation_required):
    """Print required follow-up steps, then what to try once setup is done."""
    click.echo()
    if git_status is _GitStatus.MISSING_GIT:
        click.echo(
            "Git is not installed, so this experiment has no repository yet. "
            "Install Git from https://git-scm.com/downloads, then run:"
        )
        click.echo()
        click.echo("  git init")
        click.echo()
    elif git_status is _GitStatus.INIT_FAILED:
        click.echo(
            "Setup could not initialise a Git repository here. Create one "
            "yourself before debugging or deploying:"
        )
        click.echo()
        click.echo("  git init")
        click.echo()

    if activation_required:
        click.echo(
            "Setup created this experiment's environment, but it cannot activate "
            "that environment in your shell. Activate it yourself before "
            "continuing:"
        )
        click.echo()
        click.echo("  source .venv/bin/activate")
        click.echo()
        click.echo("Then you can try running the experiment with:")
    else:
        click.echo("You can try running the experiment with the following command:")
    click.echo()
    click.echo("  psynet debug local")


def _assert_directory_is_scaffoldable():
    """Block scaffolding only when the directory name conflicts with a Python module."""
    try:
        ensure_experiment_directory_name_does_not_conflict()
    except ExperimentDirectoryNameError as exc:
        raise click.UsageError(str(exc)) from exc


def _ensure_constraints_up_to_date(ctx):
    """Create or refresh ``constraints.txt`` when missing or stale.

    Reuses an existing lockfile when it embeds the current
    ``requirements.txt`` MD5 (same freshness rule as ``psynet
    check-constraints``). Regenerates when the file is absent, empty, or
    out of date with ``requirements.txt``.
    """
    constraints_path = Path("constraints.txt")
    if constraints_path.exists() and not constraints_path.is_file():
        raise click.UsageError("constraints.txt exists but is not a regular file.")

    from .constraints_compile import (
        constraints_are_up_to_date,
        generate_constraints_file,
    )

    if constraints_are_up_to_date():
        click.echo("constraints.txt is up to date with requirements.txt.")
        return

    click.echo("Generating constraints.txt...")
    generate_constraints_file()
    if not constraints_path.is_file() or constraints_path.stat().st_size == 0:
        raise click.ClickException(
            "Failed to generate a non-empty constraints.txt file."
        )


def _scaffold_experiment(ctx, *, skip_constraints):
    """Scaffold an experiment and optionally prepare its constraints.

    In-repo experiments (demos and test experiments) keep bare ``psynet``
    requirements and omit constraints by design, so pinning and constraint
    generation are skipped there even without ``--skip-constraints``.

    When constraints are enabled, an existing bare ``psynet`` requirement is
    pinned before template files are written so a failed pin does not leave a
    half-complete scaffold. Constraints are then ensured only when missing or
    stale relative to ``requirements.txt``.
    """
    _assert_directory_is_scaffoldable()
    if is_in_repo_experiment():
        skip_constraints = True

    if not skip_constraints and Path("requirements.txt").is_file():
        try:
            pin_unpinned_psynet_requirement()
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc

    scaffold_experiment_directory()
    if not skip_constraints:
        try:
            pin_unpinned_psynet_requirement()
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        _ensure_constraints_up_to_date(ctx)


def _ensure_active_virtualenv():
    """Require setup to run inside an active virtual environment."""
    if sys.prefix == sys.base_prefix and not os.environ.get("VIRTUAL_ENV"):
        raise click.UsageError(
            "PsyNet setup must run in an active virtual environment. "
            "Create one with 'uv venv --python 3.13', then activate it before "
            "trying again."
        )


def _active_virtualenv_root():
    """Return the resolved root of the active virtual environment."""
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        return Path(virtual_env).resolve()
    return Path(sys.prefix).resolve()


def _experiment_local_virtualenv_path():
    """Return the expected dedicated virtualenv path for this experiment."""
    return (Path.cwd() / ".venv").resolve()


def _is_experiment_local_virtualenv():
    """Return whether the active interpreter is this experiment's ``./.venv``."""
    active = _active_virtualenv_root()
    expected = _experiment_local_virtualenv_path()
    return active == expected or active.is_relative_to(expected)


def _warn_foreign_virtualenv_sync(active, expected):
    """Emit a stern warning before syncing a non-experiment virtualenv."""
    click.echo(
        "Warning: synchronizing will run 'uv pip sync --strict' against "
        f"{active}, which is not this experiment's ./.venv ({expected}). "
        "That can remove or replace packages in the active environment.",
        err=True,
    )


def _resolve_foreign_virtualenv_action(*, force_foreign_env):
    """Decide whether package sync may target a non-experiment virtualenv.

    Returns ``"sync"`` or ``"cancel"``. PsyNet's shared checkout ``.venv`` is
    handled earlier by ``_resolve_shared_checkout_venv_action``; this guard
    covers other foreign environments (for example another project's
    ``.venv``). Scaffolding is intentionally allowed before this check so an
    empty experiment directory can still receive boilerplate.
    """
    if _is_psynet_checkout_virtualenv() or _is_experiment_local_virtualenv():
        return "sync"

    active = _active_virtualenv_root()
    expected = _experiment_local_virtualenv_path()
    if force_foreign_env:
        _warn_foreign_virtualenv_sync(active, expected)
        return "sync"

    summary = (
        "The active virtual environment is not this experiment's ./.venv "
        f"(active: {active}; expected: {expected}). Syncing would install "
        "packages into that environment."
    )
    if not _is_interactive():
        raise click.UsageError(
            f"{summary} Create a dedicated environment with "
            f"'uv venv --python={_recommended_python()}', activate it with "
            "'source .venv/bin/activate', install PsyNet, and re-run setup; "
            "or use --force-foreign-env to sync anyway."
        )

    click.echo(summary)
    if not click.confirm(
        "Continue syncing into the active environment?",
        default=False,
    ):
        click.echo(
            "Cancelled setup; experiment files may have been prepared, but no "
            "packages were installed."
        )
        return "cancel"

    _warn_foreign_virtualenv_sync(active, expected)
    return "sync"


def _psynet_command_env_mismatch_error():
    """Return an error if the shell venv and running PsyNet disagree.

    This catches the common footgun where a user activates a new experiment
    ``.venv`` but still invokes ``psynet`` from PsyNet's shared checkout env
    because PsyNet has not been installed into the new environment yet.
    """
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if not virtual_env:
        return None

    virtual_env_path = Path(virtual_env).resolve()
    prefix = Path(sys.prefix).resolve()
    if prefix == virtual_env_path or prefix.is_relative_to(virtual_env_path):
        return None

    install_hint = "uv pip install psynet"
    editable_source = get_editable_psynet_source()
    if editable_source is not None:
        install_hint = f"uv pip install -e {editable_source}"
    elif _is_psynet_checkout_virtualenv():
        install_hint = f"uv pip install -e {get_psynet_root()}"

    return (
        f"Your shell has VIRTUAL_ENV={virtual_env_path}, but this `psynet` "
        f"command is running from {prefix}. PsyNet is probably not installed "
        "in the activated environment yet.\n\n"
        "Finish setup with:\n"
        f"  {install_hint}\n"
        "  psynet setup\n\n"
        "If `psynet` still points at the old environment afterward, run "
        "`hash -r` or open a new shell."
    )


def _run_uv(args, description, *, quiet=False):
    """Run one uv command and report a concise Click error on failure."""
    if shutil.which("uv") is None:
        raise click.ClickException(
            "Could not find uv. Install it with 'pip install uv' and try again."
        )
    try:
        subprocess.run(
            ["uv", *args],
            check=True,
            capture_output=quiet,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = ""
        if quiet and exc.stderr:
            detail = f"\n{exc.stderr.strip()}"
        raise click.ClickException(f"Failed to {description}.{detail}") from exc


def _is_interactive():
    """Return whether setup can prompt for user choices."""
    return sys.stdin.isatty()


def _prompt_numeric_choice(title, options, *, default_index=0, intro=None):
    """Prompt for a 1-based numeric choice from ``options``.

    Parameters
    ----------
    title :
        Prompt label shown after the option list.
    options :
        Sequence of ``(value, description)`` pairs. ``value`` is returned when
        selected; ``description`` is shown to the user.
    default_index :
        Zero-based index of the default option.
    intro :
        Optional explanation printed before the numbered options.
    """
    if not options:
        raise ValueError("options must not be empty")
    if not 0 <= default_index < len(options):
        raise ValueError("default_index is out of range")

    if intro:
        click.echo(intro)
        click.echo()

    for index, (_value, description) in enumerate(options, start=1):
        marker = " (default)" if index - 1 == default_index else ""
        click.echo(f"  {index}. {description}{marker}")

    choice = click.prompt(
        title,
        type=click.IntRange(1, len(options)),
        default=default_index + 1,
    )
    return options[choice - 1][0]


_DELEGATED_SETUP_ENV_VAR = "PSYNET_SETUP_DELEGATED"


def _venv_script_path(venv_path, name):
    """Return the path of an executable inside ``venv_path``.

    PsyNet targets POSIX shells (setup guidance uses ``source .venv/bin/...``),
    so only the ``bin`` layout is handled.
    """
    return venv_path / "bin" / name


def _same_psynet_install_args():
    """Return ``uv pip install`` arguments for the PsyNet running right now.

    The dedicated environment must be bootstrapped with the *same* PsyNet that
    is running, so that the delegated setup generates experiment files and
    constraints with the version the experiment will actually use. Direct
    installs (editable checkout, VCS commit, or local path) are reproduced
    exactly; only index installs fall back to a version pin.
    """
    from .version import psynet_version

    editable_source = get_editable_psynet_source()
    if editable_source is not None:
        return ["-e", str(editable_source)]

    direct_requirement = installed_psynet_direct_requirement()
    if direct_requirement is not None:
        return [direct_requirement]

    return [f"psynet=={psynet_version}"]


def _create_dedicated_experiment_virtualenv(*, psynet_source):
    """Create ``./.venv``, install this PsyNet into it, and finish setup there.

    A process cannot activate a virtualenv in its parent shell, so setup creates
    the environment, bootstraps the same PsyNet distribution into it, and then
    re-invokes ``psynet setup`` using that environment's own entry point. Every
    experiment artifact is therefore produced by the PsyNet installed alongside
    the experiment rather than by the shared checkout that happened to launch
    setup.
    """
    if os.environ.get(_DELEGATED_SETUP_ENV_VAR):
        raise click.ClickException(
            "Delegated setup tried to create another dedicated environment. "
            "This is a bug; re-run setup from the experiment's own .venv."
        )

    venv_path = Path(".venv")
    if venv_path.exists():
        raise click.UsageError(
            "A .venv directory already exists here. Activate it with "
            "'source .venv/bin/activate', install PsyNet into it, then re-run "
            "'psynet setup', or remove it first if you want setup to recreate it."
        )

    _run_uv(
        ["venv", f"--python={_recommended_python()}"],
        "create a dedicated experiment virtual environment",
        quiet=True,
    )
    click.echo("Created ./.venv.")

    venv_path = venv_path.resolve()
    venv_python = _venv_script_path(venv_path, "python")
    _run_uv(
        ["pip", "install", "--python", str(venv_python), *_same_psynet_install_args()],
        "install PsyNet into the dedicated experiment environment",
        quiet=True,
    )
    click.echo("Installed PsyNet into ./.venv.")
    click.echo()

    _delegate_setup_to_venv(venv_path, psynet_source=psynet_source)


def _delegate_setup_to_venv(venv_path, *, psynet_source):
    """Run ``psynet setup`` again using ``venv_path``'s own entry point."""
    psynet_executable = _venv_script_path(venv_path, "psynet")
    if not psynet_executable.exists():
        raise click.ClickException(
            f"Expected a PsyNet entry point at {psynet_executable} after "
            "installing into the dedicated environment, but it is missing."
        )

    command = [str(psynet_executable), "setup"]
    if psynet_source is not None:
        command += ["--psynet-source", psynet_source]

    env = os.environ.copy()
    env[_DELEGATED_SETUP_ENV_VAR] = "1"
    env["VIRTUAL_ENV"] = str(venv_path)
    env["PATH"] = (
        str(_venv_script_path(venv_path, "python").parent)
        + os.pathsep
        + env.get("PATH", "")
    )
    # PYTHONPATH entries precede site-packages, so an inherited one pointing at
    # another PsyNet checkout would be imported instead of the PsyNet just
    # installed into venv_path, silently defeating the delegation.
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(command, env=env, check=False)
    if result.returncode != 0:
        raise click.ClickException(
            "Setup failed while running inside the dedicated environment "
            f"({psynet_executable} setup exited with code {result.returncode})."
        )


def _recommended_python():
    """Return the recommended Python major.minor for new experiment venvs."""
    from .version import recommended_python_major_minor

    return recommended_python_major_minor


def _is_psynet_checkout_virtualenv():
    """Return whether the active interpreter is PsyNet's shared checkout ``.venv``.

    Nested virtualenvs elsewhere under the checkout (for example a demo's own
    ``.venv``) are not treated as the shared development environment.
    """
    prefix = Path(sys.prefix).resolve()
    checkout_venv = (get_psynet_root() / ".venv").resolve()
    return prefix == checkout_venv or prefix.is_relative_to(checkout_venv)


def _warn_shared_checkout_sync():
    """Emit a stern warning before syncing PsyNet's shared checkout venv."""
    click.echo(
        "Warning: synchronizing will run 'uv pip sync --strict' against this "
        "shared PsyNet development environment and can remove packages that "
        "other PsyNet work depends on.",
        err=True,
    )


def _resolve_shared_checkout_venv_action(*, no_install, force_shared_env):
    """Decide how setup should treat PsyNet's shared checkout virtualenv.

    Returns ``"no-install"``, ``"sync"``, ``"new-venv"``, or ``"cancel"``.
    Raises on invalid flags. ``new-venv`` means create a dedicated environment,
    install this PsyNet into it, and finish setup there.
    """
    if no_install and force_shared_env:
        raise click.UsageError(
            "--no-install and --force-shared-env cannot be used together."
        )

    in_shared_env = _is_psynet_checkout_virtualenv()
    if force_shared_env and not in_shared_env:
        raise click.UsageError(
            "--force-shared-env is only applicable when the active virtual "
            "environment is PsyNet's shared checkout environment."
        )
    if not in_shared_env:
        return "no-install" if no_install else "sync"

    if no_install:
        return "no-install"
    if force_shared_env:
        _warn_shared_checkout_sync()
        return "sync"

    if not _is_interactive():
        raise click.UsageError(
            "The active virtual environment appears to be PsyNet's shared "
            "checkout environment. Refusing to synchronize without an explicit "
            "choice. Create a dedicated environment with "
            f"'uv venv --python={_recommended_python()}', activate it, and "
            "re-run setup; or use --no-install to scaffold and generate "
            "constraints without installing packages; or use "
            "--force-shared-env to sync anyway (this can remove packages from "
            "the shared PsyNet development environment)."
        )

    choice = _prompt_numeric_choice(
        "What do you want to do?",
        [
            (
                "new-venv",
                "Create a dedicated .venv here and finish setup in it (recommended)",
            ),
            ("cancel", "Cancel — leave everything as-is"),
            (
                "no-install",
                "Write files only — scaffold/constraints, don't install packages",
            ),
            (
                "sync",
                "Install into PsyNet's shared .venv anyway "
                "(can break other PsyNet work)",
            ),
        ],
        default_index=0,
        intro=(
            "Setup for a standalone experiment should use a dedicated "
            "virtualenv in this directory. You're currently using PsyNet's "
            "development .venv from the repository checkout, so choose how "
            "to continue:"
        ),
    )
    if choice == "cancel":
        click.echo("Cancelled setup; no experiment or environment changes were made.")
        return "cancel"
    if choice == "sync":
        _warn_shared_checkout_sync()
    return choice


def _editable_checkout_is_dirty(source):
    """Return whether an editable PsyNet checkout has uncommitted changes."""
    result = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


_EDITABLE_SOURCE_DESCRIPTIONS = {
    "editable": (
        "Editable — point requirements at this local checkout "
        "(includes uncommitted changes)"
    ),
    "commit": (
        "Git commit pin — record a specific PsyNet Git commit URL "
        "(the commit must already be pushed)"
    ),
    "existing": "Existing — keep the current PsyNet entry in requirements.txt",
}


def _editable_source_context(source):
    """Return ``(existing_requirement, choices)`` for an editable checkout.

    ``choices`` is ``None`` when ``requirements.txt`` already records this
    editable checkout, meaning no decision is needed.
    """
    editable_requirement = editable_psynet_requirement(source)
    requirements_path = Path("requirements.txt")
    try:
        existing_requirement = (
            get_psynet_requirement() if requirements_path.is_file() else None
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if existing_requirement == editable_requirement:
        return existing_requirement, None
    choices = ["editable", "commit"]
    if existing_requirement is not None and existing_requirement.lower() != "psynet":
        choices.append("existing")
    return existing_requirement, choices


def _prompt_editable_source_choice(source, choices):
    """Prompt for how to record an editable PsyNet checkout in requirements.txt."""
    return _prompt_numeric_choice(
        "What do you want to do?",
        [(choice, _EDITABLE_SOURCE_DESCRIPTIONS[choice]) for choice in choices],
        intro=(
            f"PsyNet is installed editable from {source}.\n"
            "How should setup record it in this experiment's requirements.txt?"
        ),
    )


def _resolve_delegated_psynet_source(psynet_source):
    """Pre-resolve the editable source-recording choice before delegating setup.

    Delegated setup creates a virtualenv and installs PsyNet before it would
    reach this prompt, so asking there interrupts the flow partway through.
    Asking up front (right after the environment-choice prompt) keeps the
    delegated run non-interactive. Returns the source to forward, or ``None``
    when the delegated run can decide unambiguously (or should raise its own
    actionable error non-interactively).
    """
    if psynet_source is not None:
        return psynet_source
    source = get_editable_psynet_source()
    if source is None:
        return None
    _existing, choices = _editable_source_context(source)
    if choices is None or not _is_interactive():
        return None
    return _prompt_editable_source_choice(source, choices)


def _choose_editable_psynet_requirement(source, requested_source):
    """Resolve how setup should represent an active editable PsyNet checkout."""
    editable_requirement = editable_psynet_requirement(source)
    existing_requirement, choices = _editable_source_context(source)
    if choices is None and requested_source is None:
        return editable_requirement
    if choices is None:
        choices = ["editable", "commit"]

    if requested_source is None:
        if not _is_interactive():
            options = ", ".join(f"--psynet-source {choice}" for choice in choices)
            raise click.UsageError(
                f"PsyNet is installed editable from {source}. Choose how setup "
                f"should record it in this experiment's requirements.txt with "
                f"one of: {options}."
            )
        requested_source = _prompt_editable_source_choice(source, choices)
    elif requested_source not in choices:
        raise click.UsageError(
            f"--psynet-source {requested_source} is unavailable for this experiment."
        )

    if requested_source == "editable":
        return editable_requirement
    if requested_source == "existing":
        return existing_requirement

    try:
        requirement = commit_psynet_requirement(source)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if _editable_checkout_is_dirty(source):
        click.echo(
            "Warning: the commit pin excludes uncommitted changes in the editable "
            "PsyNet checkout.",
            err=True,
        )
    return requirement


def _default_no_install_psynet_source():
    """Choose a non-interactive PsyNet source for no-install setup.

    Prefer retaining an explicit requirements pin; otherwise use the editable
    checkout. Bare ``psynet`` falls through to editable.
    """
    requirements_path = Path("requirements.txt")
    if not requirements_path.is_file():
        return "editable"
    try:
        existing_requirement = get_psynet_requirement()
    except ValueError:
        return "editable"
    if existing_requirement is not None and existing_requirement.lower() != "psynet":
        return "existing"
    return "editable"


def _echo_in_repo_setup_success():
    """Explain that bundled demos use the repository development environment."""
    click.echo(
        "This folder is a PsyNet bundled demo or test experiment. "
        "Prepared ignored boilerplate only; the PsyNet repository's "
        "development .venv is used on purpose, and setup does not install "
        "packages here.\n\n"
        "To make a standalone experiment, copy the folder outside the PsyNet "
        "repo, then run:\n"
        f"  uv venv --python {_recommended_python()}\n"
        "  source .venv/bin/activate\n"
        "  uv pip install psynet\n"
        "  psynet setup"
    )
    _handle_setup_services(mode="verify")


def _echo_no_install_success(*, docker):
    """Print success and next steps after a files-only setup."""
    _ensure_git_repository()
    if docker:
        click.echo(
            "Prepared experiment files for Docker "
            "(scaffolded boilerplate and constraints; did not install packages "
            "into the local virtual environment).\n\n"
            "Next steps:\n"
            "  Follow the generated instructions under docker/docs."
        )
        _handle_setup_services(mode="verify")
        return

    click.echo(
        "Prepared experiment files without installing packages "
        "(scaffolded boilerplate and constraints).\n\n"
        "Next steps:\n"
        "  Make sure this directory's dedicated .venv is active and PsyNet is "
        "installed in it, then run:\n"
        "  psynet setup\n"
        "  (omit --no-install / --docker so setup can install from "
        "constraints.txt)"
    )
    _handle_setup_services(mode="ensure-soft")


def _handle_setup_services(*, mode):
    """Run post-setup service guidance without blocking soft setup paths.

    Parameters
    ----------
    mode :
        ``"verify"`` checks only (in-repo / Docker). ``"ensure-soft"`` may
        offer to start Docker services but never fails setup.
    """
    from .services import ensure_local_services, verify_local_services

    click.echo()
    if mode == "verify":
        verify_local_services(strict=False)
        return
    if mode == "ensure-soft":
        ensure_local_services(assume_yes=False, strict=False)
        return
    raise ValueError(f"Unknown setup services mode: {mode}")


def setup_experiment(
    ctx,
    *,
    psynet_source,
    no_install,
    force_shared_env,
    force_foreign_env=False,
    docker=False,
):
    """Scaffold and synchronize an experiment's dedicated virtual environment."""
    if is_in_repo_experiment():
        _scaffold_experiment(ctx, skip_constraints=True)
        _echo_in_repo_setup_success()
        return

    _ensure_active_virtualenv()
    mismatch = _psynet_command_env_mismatch_error()
    if mismatch is not None:
        raise click.UsageError(mismatch)

    action = _resolve_shared_checkout_venv_action(
        no_install=no_install,
        force_shared_env=force_shared_env,
    )
    if action == "cancel":
        return
    if action == "new-venv":
        psynet_source = _resolve_delegated_psynet_source(psynet_source)
        _create_dedicated_experiment_virtualenv(psynet_source=psynet_source)
        return

    # No-install already answered the shared-env question; don't add a second
    # interactive menu. Keep an explicit pin if present, otherwise use editable.
    if (
        action == "no-install"
        and psynet_source is None
        and get_editable_psynet_source() is not None
    ):
        psynet_source = _default_no_install_psynet_source()

    editable_source = get_editable_psynet_source()
    if editable_source is None:
        if psynet_source is not None:
            raise click.UsageError(
                "--psynet-source is only needed when PsyNet is installed editable."
            )
        _scaffold_experiment(ctx, skip_constraints=False)
    else:
        requirement = _choose_editable_psynet_requirement(
            editable_source,
            psynet_source,
        )
        _scaffold_experiment(ctx, skip_constraints=True)
        set_psynet_requirement(requirement)
        _ensure_constraints_up_to_date(ctx)

    if action == "no-install":
        _echo_no_install_success(docker=docker)
        return

    if (
        _resolve_foreign_virtualenv_action(force_foreign_env=force_foreign_env)
        == "cancel"
    ):
        return

    _run_uv(
        [
            "pip",
            "sync",
            "constraints.txt",
            "--strict",
        ],
        "synchronize experiment dependencies",
    )
    _run_uv(["pip", "check"], "verify experiment dependencies")
    git_status = _ensure_git_repository()
    click.echo("Setup complete.")
    _handle_setup_services(mode="ensure-soft")
    _echo_useful_commands(
        git_status=git_status,
        activation_required=_setup_was_delegated(),
    )
