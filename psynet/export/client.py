"""Client-side export: preflight, transport choice, streamed download, publication.

Why this module exists
----------------------
The experimenter's machine used to obtain exports in two incompatible ways: it
either downloaded a complete archive into memory from the dashboard, or it
downloaded the raw database, wiped the local Postgres database, re-ingested the
data, and rebuilt the export locally. The first buffered whole multi-gigabyte
archives in RAM; the second was destructive and depended on local experiment
code matching the deployment exactly.

This module replaces both with a single client-side pipeline that never
executes experiment code and never touches a local database:

1. Ask the deployment who it is (:mod:`psynet.export.identity`).
2. Choose a transport: stream a complete server-built archive, or stream a small
   core snapshot and fetch only the asset bytes this machine is missing.
3. Extract into a staging directory beside the destination.
4. Validate, then publish atomically.

Design constraints
------------------
* **A failed export must never destroy a previous good one.** Nothing is moved
  at the destination until the new export is complete and validated. This is why
  publication is a separate, last step rather than "clear the directory, then
  fill it".
* **Downloads stream to disk.** ``response.content`` is never used, so client
  memory does not scale with archive size.
* **Incremental transfer is an optimization, never a requirement.** Any
  ineligible asset selection, missing digest, or absent ``rsync`` falls back to
  the complete archive, and says so.
* The asset cache is content-addressed, so re-exporting a deployment whose
  recordings have not changed transfers almost nothing.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode

from psynet.utils import get_logger

from .identity import ProjectIdentity
from .path_safety import (
    DATABASE_LAYOUT,
    AmbiguousArchiveLayoutError,
    UnsafePathError,
    assert_semantic_asset_path,
    extract_zip_contained,
    table_csv_members,
)

logger = get_logger()

_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

#: Manifest ``type`` values whose bytes cannot come from remote LocalStorage.
_INELIGIBLE_ASSET_TYPES = ("on_demand_asset", "external_asset")


class TransferError(Exception):
    """Raised when an export could not be transferred or published."""


@dataclass
class DashboardEndpoint:
    """Authenticated dashboard of a running experiment."""

    base_url: str
    auth: tuple[str, str]

    def url(self, path: str, **params) -> str:
        query = f"?{urlencode(params)}" if params else ""
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}{query}"


###############
#  preflight  #
###############


_OLD_DEPLOYMENT_PREFLIGHT_MESSAGE = (
    "This deployment is running an earlier version of PsyNet, incompatible with "
    "the one installed in this environment. Please install the earlier version "
    "(see constraints.txt) and try again, or log in to the dashboard and export "
    "from there."
)


def fetch_preflight(endpoint: DashboardEndpoint, *, timeout=60) -> dict:
    """Ask the deployment to describe itself.

    Raises
    ------
    TransferError
        If the deployment has no preflight endpoint (it predates this export
        protocol), or the endpoint cannot be read. This client does not
        download from deployments it cannot identify.
    """
    import requests

    try:
        response = requests.get(
            endpoint.url("dashboard/export/preflight"),
            auth=endpoint.auth,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise TransferError(
            f"Could not reach the export preflight endpoint: {exc}"
        ) from exc

    if response.status_code == 404:
        raise TransferError(_OLD_DEPLOYMENT_PREFLIGHT_MESSAGE)
    if response.status_code != 200:
        raise TransferError(
            "The export preflight endpoint returned "
            f"{response.reason} ({response.status_code})."
        )
    try:
        return response.json()
    except ValueError as exc:
        raise TransferError(
            f"The export preflight response was not valid JSON: {exc}"
        ) from exc


def choose_transport(
    identity: Optional[ProjectIdentity],
    *,
    assets: str,
    over_ssh: bool,
    requested: str = "auto",
) -> str:
    """Decide how to transfer an export.

    Parameters
    ----------
    identity :
        Preflight identity from a deployment that supports this export protocol.
    assets :
        Requested asset selection.
    over_ssh :
        Whether the client can reach the deployment's files over SSH.
    requested :
        ``auto``, ``archive``, or ``incremental``.

    Returns
    -------
    str
        ``"archive"`` or ``"incremental"``.

    Raises
    ------
    TransferError
        If ``identity`` is missing, or ``requested`` is ``incremental`` for a
        selection the deployment cannot serve that way.
    """
    if identity is None:
        raise TransferError(_OLD_DEPLOYMENT_PREFLIGHT_MESSAGE)
    if requested == "archive":
        return "archive"
    if not over_ssh:
        return "archive"
    if assets in identity.incremental_asset_modes:
        return "incremental"
    if requested == "incremental":
        raise TransferError(
            f"This deployment cannot serve --assets {assets} over incremental "
            "transfer. Use --transfer archive instead."
        )
    return "archive"


##############
#  download  #
##############


def download_archive(
    endpoint: DashboardEndpoint,
    destination_file: str,
    *,
    assets: str,
    asset_bytes: str = "include",
    progress: Optional[Callable[[int], None]] = None,
) -> str:
    """Stream an export archive from the dashboard to ``destination_file``.

    ``asset_bytes="manifest"`` requests a core snapshot that describes the
    selected assets without copying their bytes.
    """
    import requests

    url = endpoint.url(
        "dashboard/export/download", assets=assets, asset_bytes=asset_bytes
    )
    with requests.get(url, auth=endpoint.auth, stream=True) as response:
        if response.status_code != 200:
            raise TransferError(_describe_failed_response(response))
        os.makedirs(os.path.dirname(os.path.abspath(destination_file)), exist_ok=True)
        transferred = 0
        with open(destination_file, "wb") as handle:
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                handle.write(chunk)
                transferred += len(chunk)
                if progress is not None:
                    progress(transferred)
    return destination_file


def _describe_failed_response(response) -> str:
    message = (
        f"Failed to export data. The dashboard responded "
        f"{response.reason} ({response.status_code})."
    )
    try:
        reason = response.json().get("message")
    except ValueError:
        reason = None
    if reason:
        message += f" Reason: {reason}."
    return message


def extract_archive(zip_path: str, staging_dir: str) -> dict:
    """Extract a downloaded archive into ``staging_dir`` and return its manifest.

    Layout is classified before any members are unpacked, so mixed
    ``database/`` + ``data/`` zips and duplicate table members fail closed.
    Legacy ``data/`` table CSVs are for ``psynet load`` and ``--archive``, not
    for ``psynet export``.

    Raises
    ------
    TransferError
        If the archive is corrupt, ambiguous, or not a PsyNet export.
    """
    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            manifest = _read_manifest_member(archive)
            members = table_csv_members(archive)
            if members and not members[0].startswith(f"{DATABASE_LAYOUT}/"):
                raise TransferError(
                    "The downloaded archive stores table CSVs under data/, which "
                    "psynet export no longer publishes. Use psynet load or "
                    "--archive to read a legacy database.zip."
                )
            extract_zip_contained(archive, str(staging))
    except AmbiguousArchiveLayoutError as exc:
        raise TransferError(
            f"The downloaded export archive has an ambiguous layout: {exc}"
        ) from exc
    except (zipfile.BadZipFile, OSError, UnsafePathError) as exc:
        raise TransferError(
            f"The downloaded export archive is not readable: {exc}"
        ) from exc

    # Older exports bundled the experiment source; the canonical product does not.
    leftover_source = staging / "source_code.zip"
    if leftover_source.exists():
        leftover_source.unlink()

    if not (staging / "database").is_dir():
        raise TransferError(
            "The downloaded archive does not contain a database/ directory, so "
            "it is not a PsyNet export."
        )
    return manifest


def _read_manifest_member(archive: zipfile.ZipFile) -> dict:
    try:
        with archive.open("manifest.json") as handle:
            return json.load(handle)
    except KeyError:
        logger.warning(
            "The downloaded export has no manifest.json, so its project "
            "identity could not be confirmed."
        )
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransferError(
            f"The downloaded export has an unreadable manifest.json: {exc}"
        ) from exc


##############
# publishing #
##############


def staging_path_for(destination: str) -> Path:
    """Return a staging directory beside ``destination`` on the same filesystem."""
    destination = Path(os.path.expanduser(destination)).absolute()
    return destination.with_name(f".{destination.name}.incoming-{os.getpid()}")


def publish_export(
    staging_dir: str,
    destination: str,
    *,
    rotate_history: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """Move a completed staging tree to ``destination`` without risking the old one.

    Parameters
    ----------
    rotate_history :
        Optional callable that archives an existing export at ``destination``
        and returns where it was moved to (see
        :meth:`psynet.experiment.Experiment.rotate_export_history`). When
        omitted, an existing destination is displaced to a temporary sibling and
        removed only once the new export is in place.

    Notes
    -----
    Either way the previous export survives a failure: on error it is moved
    back to ``destination``, whether it was displaced to a temporary sibling or
    rotated into the history directory. If that restoration also fails, the
    previous tree is left at its recovery path and both locations are reported.
    """
    staging = Path(staging_dir)
    target = Path(os.path.expanduser(destination)).absolute()
    if not staging.is_dir():
        raise TransferError(f"Nothing to publish: {staging} is not a directory.")
    target.parent.mkdir(parents=True, exist_ok=True)

    displaced = None
    rotated = None
    if target.exists():
        if rotate_history is not None:
            rotated = rotate_history(str(target))
        else:
            displaced = target.with_name(f".{target.name}.superseded-{os.getpid()}")
            shutil.rmtree(displaced, ignore_errors=True)
            target.rename(displaced)

    try:
        os.replace(str(staging), str(target))
    except (OSError, KeyboardInterrupt) as exc:
        previous = displaced or (Path(rotated) if rotated else None)
        restored = False
        if previous is not None and previous.exists() and not target.exists():
            try:
                previous.rename(target)
                restored = True
                displaced = None
            except OSError:
                logger.warning(
                    "Could not restore the previous export to %s; it remains at %s.",
                    target,
                    previous,
                )
        if previous is not None and not restored:
            raise TransferError(
                f"Could not publish the export to {target}: {exc} "
                f"The previous export was kept at {previous}."
            ) from exc
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise TransferError(f"Could not publish the export to {target}: {exc}") from exc
    if displaced is not None:
        shutil.rmtree(displaced, ignore_errors=True)
    return str(target)


###########################
# incremental asset fetch #
###########################


@dataclass
class AssetTransferPlan:
    """Assets that an incremental transfer must hydrate from the remote host."""

    rows: list[dict]
    digests: list[str]
    ineligible: list[dict]

    @property
    def eligible(self) -> bool:
        return not self.ineligible


def plan_asset_transfer(staging_dir: str) -> AssetTransferPlan:
    """Read ``assets/manifest.csv`` and decide whether rsync can supply the bytes."""
    manifest_path = Path(staging_dir) / "assets" / "manifest.csv"
    if not manifest_path.exists():
        raise TransferError(
            "The incremental export did not contain assets/manifest.csv."
        )

    with manifest_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    digests: list[str] = []
    ineligible: list[dict] = []
    seen = set()
    for row in rows:
        asset_type = (row.get("type") or "").lower()
        if asset_type == "external_asset":
            # URL-only; nothing to transfer.
            continue
        if asset_type in _INELIGIBLE_ASSET_TYPES:
            ineligible.append(row)
            continue
        if row.get("storage") != "LocalStorage":
            ineligible.append(row)
            continue
        digest = row.get("sha256_contents")
        if not digest:
            ineligible.append(row)
            continue
        if digest not in seen:
            seen.add(digest)
            digests.append(digest)
    return AssetTransferPlan(rows=rows, digests=digests, ineligible=ineligible)


def hydrate_assets(
    staging_dir: str,
    plan: AssetTransferPlan,
    *,
    rsync_source: str,
    ssh_command=None,
    cache_root=None,
) -> int:
    """Fetch missing asset objects and link them into the staging export tree.

    Returns
    -------
    int
        Number of asset entries materialized in the export tree.
    """
    from .asset_cache import link_or_copy, object_cache_path
    from .ssh_rsync import (
        RsyncRequiredError,
        missing_object_digests,
        prefetch_missing_objects,
    )

    if not plan.eligible:
        raise TransferError(
            f"{len(plan.ineligible)} selected asset(s) cannot be transferred "
            "incrementally."
        )
    # Validate every semantic path before transferring anything, so a manifest
    # that would write outside the export tree fails closed even when the
    # transfer itself cannot run (for example when rsync is unavailable).
    safe_export_paths = {}
    for row in plan.rows:
        export_path = row.get("export_path")
        if not row.get("sha256_contents") or not export_path:
            continue
        try:
            safe_export_paths[export_path] = assert_semantic_asset_path(export_path)
        except UnsafePathError as exc:
            raise TransferError(
                f"Asset export path is not contained in the export tree: {exc}"
            ) from exc

    if plan.digests:
        try:
            prefetch_missing_objects(
                plan.digests,
                source=rsync_source,
                ssh_command=ssh_command,
                cache_root=cache_root,
            )
        except subprocess.CalledProcessError as exc:
            # Exit 23 in particular means rsync could not read some of the
            # requested objects, which the server itself can still read.
            raise TransferError(
                f"rsync failed with exit code {exc.returncode} while copying "
                "asset objects from the server."
            ) from exc
        except RsyncRequiredError as exc:
            raise TransferError(str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise TransferError(
                f"Incremental asset transfer could not copy objects: {exc}"
            ) from exc
        remaining = missing_object_digests(plan.digests, cache_root=cache_root)
        if remaining:
            raise TransferError(
                f"{len(remaining)} asset object(s) are still missing from the "
                "local cache after rsync."
            )

    assets_root = Path(staging_dir) / "assets"
    materialized = 0
    for row in plan.rows:
        digest = row.get("sha256_contents")
        export_path = row.get("export_path")
        if not digest or not export_path:
            continue
        destination = assets_root / safe_export_paths[export_path]
        if destination.exists():
            continue
        is_folder = str(row.get("is_folder", "")).lower() in ("true", "1")
        link_or_copy(
            object_cache_path(digest, cache_root), destination, is_folder=is_folder
        )
        materialized += 1
    return materialized


def _server_address(server: str) -> tuple[str, Optional[str]]:
    from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

    server_info = CONFIGURED_HOSTS[server]
    return server_info["host"], server_info.get("user")


class SshSession:
    """One SSH connection, reused across the steps of a single export.

    One export probes for rsync, asks for the remote home directory, and
    fetches ``logs.jsonl``. Opening a connection per step made a small export
    pay several SSH handshakes, which dominated the runtime once the payload
    was cached. The connection is therefore opened lazily and shared, but its
    lifetime is bounded by this object rather than by the process, so a dead
    connection is not served to later exports and sockets are always closed.
    """

    def __init__(self, server: str):
        self.server = server
        self._executor = None

    @property
    def executor(self):
        if self._executor is None:
            from dallinger.command_line.docker_ssh import Executor

            ssh_host, ssh_user = _server_address(self.server)
            self._executor = Executor(ssh_host, user=ssh_user)
        return self._executor

    def close(self) -> None:
        executor, self._executor = self._executor, None
        if executor is None:
            return
        try:
            executor.client.close()
        except Exception as exc:
            logger.warning("Could not close the SSH connection: %s", exc)

    def __enter__(self) -> "SshSession":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def fetch_logs(
    staging_dir: str, *, app: str, server: str, session: SshSession
) -> Optional[str]:
    """Copy the deployment's ``logs.jsonl`` into the staging export tree.

    Logs are a convenience, so a failure here warns rather than aborting the
    export.
    """
    local_path = os.path.join(staging_dir, "logs.jsonl")
    try:
        executor = session.executor
        home = executor.run("echo $HOME", raise_=False).strip()
        # Opening SFTP on the existing client reuses the transport rather than
        # negotiating a second connection.
        sftp = executor.client.open_sftp()
        try:
            sftp.get(f"{home}/dallinger/{app}/logs.jsonl", local_path)
        finally:
            sftp.close()
    except Exception as exc:
        logger.warning("Could not export logs.jsonl from %s: %s", server, exc)
        return None
    return local_path


def ssh_rsync_source(server: str, session: SshSession) -> tuple[str, list]:
    """Return the rsync source spec and ssh options for a configured SSH server."""
    from dallinger.command_line.utils import get_server_pem_path

    from .ssh_rsync import default_ssh_command, remote_assets_source

    ssh_host, ssh_user = _server_address(server)
    home = session.executor.run("echo $HOME").strip()
    return (
        remote_assets_source(ssh_host, ssh_user, home),
        default_ssh_command(get_server_pem_path()),
    )


def ssh_rsync_available(server: str, session: SshSession) -> bool:
    """Return whether both ends of the SSH connection have ``rsync``."""
    from .ssh_rsync import (
        emit_rsync_missing_warning,
        local_rsync_available,
    )

    if not local_rsync_available():
        emit_rsync_missing_warning(location="local")
        return False
    ssh_host, _ = _server_address(server)
    try:
        if not session.executor.run("command -v rsync", raise_=False).strip():
            emit_rsync_missing_warning(location="remote", host=ssh_host)
            return False
    except Exception as exc:
        logger.warning("Could not check for rsync on %s: %s", ssh_host, exc)
        return False
    return True
