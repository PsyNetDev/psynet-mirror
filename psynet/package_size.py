"""Deployment-plan size limit for experiment packages.

The default ceiling is sized so authors can bake public audiovisual stimuli
into ``static/`` without hitting the old 256 MB tripwire. PsyNet's own
pre-check caps Heroku deploys at 500 MB whatever ``EXP_MAX_SIZE_MB`` says.
Raise ``EXP_MAX_SIZE_MB`` only after reviewing ``dallinger deployment-files list``.

Importing PsyNet calls :func:`apply_default_exp_max_size_mb` (see
``psynet.runtime_init``), so Dallinger's own size check and child processes
see the same default.
"""

from __future__ import annotations

import os

import click

DEFAULT_EXP_MAX_SIZE_MB = 1024
EXP_MAX_SIZE_MB_ENV = "EXP_MAX_SIZE_MB"
HEROKU_MAX_SLUG_MB = 500


def apply_default_exp_max_size_mb() -> None:
    """Expose PsyNet's default to Dallinger's own size check."""
    os.environ.setdefault(EXP_MAX_SIZE_MB_ENV, str(DEFAULT_EXP_MAX_SIZE_MB))


def get_exp_max_size_mb(*, heroku: bool = False) -> int:
    """Return the configured deployment-plan size limit in megabytes (10**6 bytes).

    Reading the limit does not write ``EXP_MAX_SIZE_MB``.
    """
    raw = os.environ.get(EXP_MAX_SIZE_MB_ENV)
    if raw is None:
        configured = DEFAULT_EXP_MAX_SIZE_MB
    else:
        try:
            configured = int(raw)
        except ValueError:
            configured = 0
        if configured <= 0:
            raise click.UsageError(
                f"{EXP_MAX_SIZE_MB_ENV} must be a positive integer number of "
                f"megabytes (got {raw!r})."
            )
    if heroku:
        return min(configured, HEROKU_MAX_SLUG_MB)
    return configured


def package_size_limit_error(
    size_in_mb: float, max_size_in_mb: int, *, heroku: bool = False
) -> str:
    """Build the error shown when an experiment package is too large."""
    message = (
        f"Your experiment deployment plan is {size_in_mb:.1f} MB, which exceeds "
        f"the {max_size_in_mb} MB limit."
    )
    if heroku:
        message += (
            " This is a pre-check of the deployment-plan size (what deploy.toml "
            "would copy), not a measurement of the built slug."
        )
        if max_size_in_mb >= HEROKU_MAX_SLUG_MB:
            message += (
                f" Heroku slugs cannot exceed {HEROKU_MAX_SLUG_MB} MB; host large "
                "public media on S3 or deploy with Docker/SSH."
            )
        else:
            message += (
                f" The bound that fired is {EXP_MAX_SIZE_MB_ENV}={max_size_in_mb}. "
                f"Heroku slugs still cannot exceed {HEROKU_MAX_SLUG_MB} MB."
            )
        message += (
            " Run 'dallinger deployment-files list' and exclude files in deploy.toml."
        )
        return message
    if max_size_in_mb == DEFAULT_EXP_MAX_SIZE_MB:
        message += (
            f" The default {DEFAULT_EXP_MAX_SIZE_MB} MB ceiling is meant for baking "
            "public stimuli into static/."
        )
        override = f"set {EXP_MAX_SIZE_MB_ENV} to override this limit"
    else:
        message += (
            f" This limit comes from {EXP_MAX_SIZE_MB_ENV}={max_size_in_mb}; PsyNet's "
            f"default of {DEFAULT_EXP_MAX_SIZE_MB} MB is meant for baking public "
            "stimuli into static/."
        )
        override = f"raise {EXP_MAX_SIZE_MB_ENV}"
    return (
        message + " Run 'dallinger deployment-files list' to see what is included, "
        f"then exclude junk in deploy.toml. If the size is intentional, {override}. "
        "Do not use that override to ship generated files, recordings, or private "
        "data; those belong in PsyNet's asset system. Heroku slugs cannot "
        f"exceed {HEROKU_MAX_SLUG_MB} MB, so host large media outside the "
        "package or deploy with Docker/SSH."
    )
