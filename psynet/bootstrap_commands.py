"""Shared Click commands for the bootstrap and full PsyNet CLIs.

``setup``, ``scripts``, ``services``, and ``generate-constraints`` are
registered on both the thin bootstrap group and the full
``psynet.command_line`` group. Keeping a single definition prevents
option/help drift (for example ``--force-foreign-env``).

These commands must remain importable without ``psynet[experiment]`` or
Dallinger. Heavy imports stay inside command bodies.
"""

from __future__ import annotations

from pathlib import Path

import click

from psynet.experiment_scaffold import (
    PRUNE_COMMAND_HELP,
    PRUNE_INCLUDE_MODIFIED_OPTION_HELP,
    PRUNE_INCLUDE_TRACKED_OPTION_HELP,
)


@click.command("setup")
@click.option(
    "--psynet-source",
    type=click.Choice(["editable", "commit", "existing"]),
    default=None,
    help="How to represent an active editable PsyNet installation.",
)
@click.option(
    "--no-install",
    is_flag=True,
    help="Scaffold and generate constraints without installing packages.",
)
@click.option(
    "--force-shared-env",
    is_flag=True,
    help="Allow synchronizing PsyNet's shared checkout virtual environment.",
)
@click.option(
    "--force-foreign-env",
    is_flag=True,
    help=(
        "Allow synchronizing a virtual environment that is not this "
        "experiment's ./.venv."
    ),
)
@click.pass_context
def setup(ctx, psynet_source, no_install, force_shared_env, force_foreign_env):
    """Scaffold and synchronize an experiment's dedicated virtual environment."""
    from psynet.experiment_setup import setup_experiment

    setup_experiment(
        ctx,
        psynet_source=psynet_source,
        no_install=no_install,
        force_shared_env=force_shared_env,
        force_foreign_env=force_foreign_env,
    )


@click.group("scripts")
def scripts():
    """Manage experiment boilerplate scripts and templates."""
    pass


@scripts.command("scaffold")
@click.option(
    "--skip-constraints",
    is_flag=True,
    help="Do not pin PsyNet or generate constraints.txt.",
)
@click.pass_context
def scripts_scaffold(ctx, skip_constraints):
    """Create any missing PsyNet boilerplate files for the experiment directory.

    If ``experiment.py`` or ``requirements.txt`` are missing, starter versions are
    created as well. For standalone experiments, also pins a bare ``psynet``
    requirement and generates ``constraints.txt`` unless ``--skip-constraints``
    is set (or the directory is a PsyNet bundled demo/test experiment).
    """
    from psynet.experiment_setup import _scaffold_experiment

    _scaffold_experiment(ctx, skip_constraints=skip_constraints)


@scripts.command("update")
@click.pass_context
def scripts_update(ctx):
    """Overwrite experiment boilerplate with the latest PsyNet templates.

    Existing ``config.txt``, ``README.md``, and ``deploy.toml`` files are
    preserved. PsyNet-managed Agent Skills under ``.cursor/skills/psynet`` are
    refreshed; other skill directories under ``.cursor/skills/`` are
    preserved. Recognized generated ``docker/`` helper scripts are deleted;
    customized copies are preserved.
    """
    from psynet.experiment_scaffold import scaffold_experiment_directory
    from psynet.light_utils import (
        ExperimentDirectoryNameError,
        ensure_experiment_directory_name_does_not_conflict,
    )

    try:
        ensure_experiment_directory_name_does_not_conflict()
    except ExperimentDirectoryNameError as e:
        raise click.UsageError(str(e)) from e
    if not Path("experiment.py").is_file():
        raise click.UsageError(
            "The current directory is not a valid PsyNet experiment "
            "(missing experiment.py)."
        )
    scaffold_experiment_directory(overwrite=True)


@scripts.command("prune", help=PRUNE_COMMAND_HELP)
@click.option(
    "--include-modified",
    is_flag=True,
    help=PRUNE_INCLUDE_MODIFIED_OPTION_HELP,
)
@click.option(
    "--include-tracked",
    is_flag=True,
    help=PRUNE_INCLUDE_TRACKED_OPTION_HELP,
)
@click.pass_context
def scripts_prune(ctx, include_modified, include_tracked):
    """Remove scaffold-managed boilerplate files from the experiment directory."""
    from psynet.experiment_scaffold import run_scripts_prune
    from psynet.light_utils import (
        ExperimentDirectoryNameError,
        ensure_experiment_directory_name_does_not_conflict,
    )

    try:
        ensure_experiment_directory_name_does_not_conflict()
    except ExperimentDirectoryNameError as e:
        raise click.UsageError(str(e)) from e
    if not Path("experiment.py").is_file():
        raise click.UsageError(
            "The current directory is not a valid PsyNet experiment "
            "(missing experiment.py)."
        )
    run_scripts_prune(
        include_modified=include_modified, include_tracked=include_tracked
    )


@click.group("services")
def services():
    """Check and ensure local PostgreSQL and Redis services."""
    pass


@services.command("check")
def services_check():
    """Verify that local PostgreSQL and Redis are reachable.

    Does not start services. Exits with an error if either is unavailable.
    """
    from psynet.services import verify_local_services

    verify_local_services(strict=True)


@services.command("ensure")
@click.option(
    "--yes",
    "assume_yes",
    is_flag=True,
    help="Start missing services with Docker without prompting.",
)
def services_ensure(assume_yes):
    """Ensure local PostgreSQL and Redis are reachable.

    If a service is missing, offers to start Docker containers that publish
    localhost ports 5432 and 6379 (what virtualenv ``psynet debug local``
    expects). Exits with an error if services remain unavailable.
    """
    from psynet.services import ensure_local_services

    ensure_local_services(assume_yes=assume_yes, strict=True)


@click.command("generate-constraints")
def generate_constraints():
    """Generate constraints.txt from requirements.txt."""
    from psynet.constraints_compile import generate_constraints_file

    generate_constraints_file()


def register_bootstrap_commands(group: click.Group) -> None:
    """Attach shared thin-bootstrap commands to ``group``."""
    group.add_command(setup)
    group.add_command(scripts)
    group.add_command(services)
    group.add_command(generate_constraints)
