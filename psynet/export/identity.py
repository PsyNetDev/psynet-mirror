"""Project identity and export-format compatibility checks.

Why this module exists
----------------------
An export can take a long time and produce many gigabytes. The most expensive
mistakes are cheap to detect first: running ``psynet export ssh`` from the wrong
experiment directory, or pointing a new client at a deployment whose export
format it cannot read. Both used to be discovered only after the transfer, or
not at all.

The deployed experiment answers a small authenticated preflight
(``/dashboard/export/preflight``) describing what it is; this module compares
that answer with the local experiment directory and decides whether to proceed.

Design constraints
------------------
* A wrong *experiment label* is almost always a wrong directory, so it blocks by
  default. A differing or dirty *Git commit* is common during development, so it
  only warns, and asks for confirmation when a terminal is attached.
* An unreadable ``export_format_version`` is a hard error: silently downloading
  an archive we cannot parse is worse than failing.
* PsyNet and Dallinger version differences are recorded, not enforced, because
  no local ORM or experiment code takes part in building a remote export.
* A deployment without the preflight endpoint is an earlier PsyNet than this
  environment. Export stops immediately; install that version (see
  ``constraints.txt``) or export from the dashboard.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from typing import Optional

from psynet.utils import get_logger

from .paths import EXPORT_FORMAT_VERSION

logger = get_logger()

#: Export-format versions this client knows how to read.
SUPPORTED_EXPORT_FORMAT_VERSIONS = (1,)


class ProjectMismatch(Exception):
    """Raised when an export's project identity does not match the local one."""


@dataclass
class ProjectIdentity:
    """What an export claims to be, or what the local directory expects."""

    experiment_label: Optional[str] = None
    deployment_id: Optional[str] = None
    git_commit_sha: Optional[str] = None
    git_dirty: Optional[bool] = None
    psynet_version: Optional[str] = None
    dallinger_version: Optional[str] = None
    export_format_version: Optional[int] = None
    #: Asset selections the deployment can serve over incremental transfer.
    incremental_asset_modes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict) -> "ProjectIdentity":
        """Build an identity from a preflight response or export manifest."""
        known = {f.name for f in fields(cls)}
        values = {key: value for key, value in (payload or {}).items() if key in known}
        modes = values.get("incremental_asset_modes")
        if modes is not None:
            values["incremental_asset_modes"] = tuple(modes)
        version = values.get("export_format_version")
        if isinstance(version, str) and version.isdigit():
            values["export_format_version"] = int(version)
        return cls(**values)


def local_project_identity(experiment_class) -> ProjectIdentity:
    """Describe the experiment directory the command is running in."""
    from psynet import __version__ as psynet_version
    from psynet.deployment_info import _get_git_provenance

    try:
        from dallinger.version import __version__ as dallinger_version
    except Exception:
        dallinger_version = None

    try:
        git_commit_sha, git_dirty = _get_git_provenance()
    except Exception:
        logger.warning(
            "Could not determine the local Git provenance for the export "
            "identity check.",
            exc_info=True,
        )
        git_commit_sha, git_dirty = None, None

    return ProjectIdentity(
        experiment_label=experiment_class.label,
        git_commit_sha=git_commit_sha,
        git_dirty=git_dirty,
        psynet_version=psynet_version,
        dallinger_version=dallinger_version,
    )


def server_project_identity() -> dict:
    """Describe the running experiment, for the export preflight response.

    Runs inside the deployed experiment.
    """
    from psynet import __version__ as psynet_version
    from psynet.experiment import get_experiment

    try:
        from dallinger.version import __version__ as dallinger_version
    except Exception:
        dallinger_version = None

    experiment = get_experiment()
    return {
        "experiment_label": experiment.label,
        "deployment_id": experiment.deployment_id,
        "git_commit_sha": experiment.var.get("git_commit_sha", None),
        "git_dirty": experiment.var.get("git_dirty", None),
        "psynet_version": psynet_version,
        "dallinger_version": dallinger_version,
        "export_format_version": EXPORT_FORMAT_VERSION,
        "incremental_asset_modes": list(_incremental_asset_modes(experiment)),
    }


def _incremental_asset_modes(experiment) -> tuple[str, ...]:
    """Return asset selections eligible for incremental client-side transfer.

    ``none`` needs no asset bytes at all, so it is always eligible. ``collected``
    is eligible only when the deployment's asset storage keeps bytes in a local
    directory that rsync can read.
    """
    from psynet.asset import LocalStorage

    modes = ["none"]
    if isinstance(getattr(experiment, "asset_storage", None), LocalStorage):
        modes.append("collected")
    return tuple(modes)


def check_export_format_version(identity: ProjectIdentity) -> None:
    """Raise if this client cannot read the deployment's export format."""
    version = identity.export_format_version
    if version is None:
        logger.warning(
            "The export does not declare an export format version; assuming it "
            "is readable by this version of PsyNet."
        )
        return
    if version not in SUPPORTED_EXPORT_FORMAT_VERSIONS:
        supported = ", ".join(str(v) for v in SUPPORTED_EXPORT_FORMAT_VERSIONS)
        raise ProjectMismatch(
            f"The deployment produces export format version {version}, but this "
            f"version of PsyNet can only read version(s) {supported}. "
            "Upgrade PsyNet to export from this deployment."
        )


def describe_identity_problems(
    local: ProjectIdentity, remote: ProjectIdentity
) -> tuple[list[str], list[str], list[str]]:
    """Compare two identities.

    Returns
    -------
    tuple
        ``(blocking, confirmable, notes)``: differences that must stop the
        export, differences that deserve confirmation, and differences that are
        only worth reporting.
    """
    blocking = []
    warnings = []
    notes = []

    if (
        remote.experiment_label is not None
        and local.experiment_label is not None
        and remote.experiment_label != local.experiment_label
    ):
        blocking.append(
            f"The deployment's experiment label is {remote.experiment_label!r}, but "
            f"this directory contains {local.experiment_label!r}. You are probably "
            "running the export from the wrong experiment folder."
        )

    if (
        remote.git_commit_sha
        and local.git_commit_sha
        and remote.git_commit_sha != local.git_commit_sha
    ):
        warnings.append(
            f"The deployment was launched from Git commit "
            f"{remote.git_commit_sha[:12]}, but this directory is on "
            f"{local.git_commit_sha[:12]}."
        )
    if remote.git_dirty:
        warnings.append(
            "The deployment was launched from a Git working tree with "
            "uncommitted changes."
        )
    if local.git_dirty:
        warnings.append("This experiment directory has uncommitted changes.")

    for label, remote_version, local_version in (
        ("PsyNet", remote.psynet_version, local.psynet_version),
        ("Dallinger", remote.dallinger_version, local.dallinger_version),
    ):
        if remote_version and local_version and remote_version != local_version:
            notes.append(
                f"{label} {remote_version} is deployed, but {local_version} is "
                "installed locally. The export is built entirely on the server, "
                "so this does not affect its contents."
            )

    return blocking, warnings, notes


def confirm_project_identity(
    local: ProjectIdentity,
    remote: ProjectIdentity,
    *,
    allow_mismatch: bool = False,
    confirm=None,
    emit=None,
) -> None:
    """Validate ``remote`` against ``local`` before transferring anything.

    Parameters
    ----------
    allow_mismatch :
        Proceed despite non-blocking differences without asking. Required for
        non-interactive use when the deployed and local code differ.
    confirm :
        Callable taking a message and returning a boolean. Defaults to a
        terminal prompt.
    emit :
        Callable used to report warnings. Defaults to the module logger.

    Raises
    ------
    ProjectMismatch
        If the export format is unreadable, the experiment labels differ, or a
        non-blocking difference could not be confirmed.
    """
    if emit is None:

        def emit(message):
            logger.warning(message)

    check_export_format_version(remote)
    blocking, warnings, notes = describe_identity_problems(local, remote)

    for message in notes:
        emit(f"NOTE: {message}")

    if blocking:
        raise ProjectMismatch(
            "\n".join(
                blocking
                + [
                    "Refusing to export. Run the command from the deployment's "
                    "own experiment directory."
                ]
            )
        )

    if not warnings:
        return

    for message in warnings:
        emit(f"WARNING: {message}")

    if allow_mismatch:
        emit("Continuing because --allow-project-mismatch was supplied.")
        return

    if confirm is None:
        if not sys.stdin.isatty():
            raise ProjectMismatch(
                "The deployed experiment does not match this directory exactly "
                "(see the warnings above). Re-run with "
                "--allow-project-mismatch to export anyway."
            )
        from psynet.utils import user_confirms

        def confirm(message):
            return user_confirms(message)

    if not confirm(
        "The deployed experiment does not match this directory exactly. "
        "Export anyway? Press Y and Enter to continue, or just Enter to cancel."
    ):
        raise ProjectMismatch("Export cancelled.")


def identity_from_manifest(manifest: dict) -> ProjectIdentity:
    """Build an identity from a downloaded export's ``manifest.json``."""
    return ProjectIdentity.from_dict(manifest)


def identity_changed(preflight: ProjectIdentity, downloaded: ProjectIdentity) -> bool:
    """Return whether download identity disagrees with a successful preflight."""
    for name in (
        "experiment_label",
        "deployment_id",
        "git_commit_sha",
        "export_format_version",
    ):
        before = getattr(preflight, name)
        after = getattr(downloaded, name)
        if before is not None and before != after:
            return True
    return False
