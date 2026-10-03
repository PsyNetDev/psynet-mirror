"""Bulk SSH transfer of content-addressed asset objects via rsync.

Command-line SSH exports previously called Paramiko ``sftp.get`` once per
asset. Each call pays a full round trip, which dominates when exporting
many small files. This module instead copies missing
``objects/sha256/<digest>`` entries with one ``rsync --files-from`` from
the remote LocalStorage tree (``$HOME/psynet-data/assets``) into the
persistent local cache.

Design constraints
------------------
* Only SHA-256 hex digests are accepted as transfer paths, so
  ``--files-from`` cannot be used for path traversal.
* Objects are rsynced into a staging directory, hashed, and then renamed
  into the cache. A partial or corrupt transfer is never treated as a
  cache hit.
* ``-r`` is passed explicitly. Since rsync 3.0, ``-a`` does not imply
  ``--recursive`` when ``--files-from`` is used, so folder objects would
  otherwise arrive empty.
* Callers must not fall back to per-asset SFTP when rsync is missing or the
  remote copy fails; they either stop or switch to a complete server-built
  archive. S3-backed assets are not transferred this way.

This module does not import SQLAlchemy models so it can be unit-tested
without a running experiment.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Union

from psynet.export.asset_cache import (
    _cached_object_is_valid,
    _make_read_only,
    object_cache_path,
)
from psynet.utils import sha256_directory, sha256_file

logger = logging.getLogger(__name__)

_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_REMOTE_ASSETS_SUFFIX = "psynet-data/assets"


class RsyncRequiredError(RuntimeError):
    """Raised when SSH asset export needs rsync and cannot continue."""

    def __init__(self, message: Optional[str] = None):
        super().__init__(
            message
            or (
                "SSH asset export requires rsync locally and on the SSH host. "
                "Install it and re-run the export."
            )
        )


def object_relative_path(digest: str) -> str:
    """Return the content-addressed path for ``digest`` under an assets root.

    Parameters
    ----------
    digest :
        SHA-256 hex digest.

    Returns
    -------
    str
        ``objects/sha256/<digest>`` using a lowercase digest.

    Raises
    ------
    ValueError
        If ``digest`` is not a 64-character hex string.
    """
    return f"objects/sha256/{_normalize_digest(digest)}"


def missing_object_digests(
    digests: Iterable[str],
    cache_root: Optional[Union[str, Path]] = None,
) -> List[str]:
    """Return unique digests that are not yet present in the local cache."""
    missing: List[str] = []
    seen = set()
    for raw in digests:
        digest = _normalize_digest(raw)
        if digest in seen:
            continue
        seen.add(digest)
        if not _cached_object_is_valid(digest, object_cache_path(digest, cache_root)):
            missing.append(digest)
    return missing


def remote_assets_source(ssh_host: str, ssh_user: Optional[str], home_dir: str) -> str:
    """Return the rsync source spec for LocalStorage on an SSH host."""
    remote_root = f"{home_dir.rstrip('/')}/{_REMOTE_ASSETS_SUFFIX}/"
    if ssh_user:
        return f"{ssh_user}@{ssh_host}:{remote_root}"
    return f"{ssh_host}:{remote_root}"


def default_ssh_command(identity_path: Optional[Union[str, Path]]) -> List[str]:
    """Return OpenSSH options matching Dallinger's docker-ssh key usage."""
    cmd = ["ssh"]
    if identity_path is not None:
        cmd.extend(["-i", str(identity_path)])
    cmd.extend(
        [
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]
    )
    return cmd


def local_rsync_available(rsync_bin: str = "rsync") -> bool:
    """Return whether ``rsync`` is on the local ``PATH``."""
    return shutil.which(rsync_bin) is not None


def rsync_missing_warning_text(*, location: str, host: Optional[str] = None) -> str:
    """Return the user-facing warning for a missing ``rsync`` binary.

    Parameters
    ----------
    location :
        ``"local"`` when this computer lacks rsync, ``"remote"`` when the
        SSH host lacks it.
    host :
        SSH hostname, used only for the remote warning.
    """
    if location == "local":
        return (
            "WARNING: rsync is not installed on this computer.\n"
            "SSH asset export cannot copy files from the server until rsync is installed.\n"
            "\n"
            "Install rsync, then re-run the export:\n"
            "  Ubuntu/Debian:  sudo apt install rsync\n"
            "  macOS:          brew install rsync"
        )
    host_label = host or "the SSH host"
    return (
        f"WARNING: rsync is not installed on the SSH host ({host_label}).\n"
        "SSH asset export cannot copy files from the server until rsync is installed.\n"
        "\n"
        "On the server, run:\n"
        "  sudo apt install rsync\n"
        "Then re-run the export."
    )


def emit_rsync_missing_warning(*, location: str, host: Optional[str] = None) -> str:
    """Print a salient warning that rsync is missing and how to install it."""
    import click

    text = rsync_missing_warning_text(location=location, host=host)
    click.secho("\n" + text + "\n", fg="yellow", bold=True, err=True)
    logger.warning(text.replace("\n", " "))
    return text


def build_rsync_command(
    *,
    files_from: Union[str, Path],
    source: str,
    dest: str,
    ssh_command: Optional[Sequence[str]] = None,
    rsync_bin: str = "rsync",
) -> List[str]:
    """Build an ``rsync --files-from`` command as a subprocess argv list.

    ``-r`` is required in addition to ``-a``: since rsync 3.0, ``-a`` does
    not imply ``--recursive`` when ``--files-from`` is used, so folder
    objects would otherwise arrive as empty directories.
    """
    cmd = [
        rsync_bin,
        "-a",
        "-r",
        "--no-owner",
        "--no-group",
        "--delay-updates",
        "--files-from",
        str(files_from),
    ]
    if ssh_command:
        cmd.extend(["-e", shlex.join(list(ssh_command))])
    cmd.extend([_ensure_trailing_slash(source), _ensure_trailing_slash(dest)])
    return cmd


def prefetch_missing_objects(
    digests: Iterable[str],
    *,
    source: str,
    cache_root: Optional[Union[str, Path]] = None,
    ssh_command: Optional[Sequence[str]] = None,
    run: Optional[Callable] = None,
    rsync_bin: str = "rsync",
) -> List[str]:
    """Copy missing content-addressed objects from ``source`` into the cache.

    ``source`` is an rsync location: a local directory or
    ``user@host:/absolute/assets/``. Each requested digest is hashed after
    transfer and only promoted into the cache on a match.

    Parameters
    ----------
    digests :
        SHA-256 hex digests to fetch. Already-cached entries are skipped.
    source :
        Rsync source root that contains ``objects/sha256/``.
    cache_root :
        Override the default local cache root.
    ssh_command :
        Optional argv for ``rsync -e``, typically from
        :func:`default_ssh_command`.
    run :
        Injected ``subprocess.run``-compatible callable (for tests).
    rsync_bin :
        ``rsync`` executable name or path.

    Returns
    -------
    list of str
        Digests newly written to the cache, in request order.
    """
    if run is None:
        run = subprocess.run

    missing = missing_object_digests(digests, cache_root=cache_root)
    if not missing:
        return []

    cache_dir = object_cache_path(missing[0], cache_root).parents[2]
    cache_dir.mkdir(parents=True, exist_ok=True)

    written: List[str] = []
    with tempfile.TemporaryDirectory(
        prefix=".rsync-staging-", dir=cache_dir
    ) as staging:
        staging_path = Path(staging)
        list_path = staging_path / "files-from.txt"
        list_path.write_text(
            "".join(f"{object_relative_path(digest)}\n" for digest in missing)
        )
        dest = staging_path / "incoming"
        dest.mkdir()
        cmd = build_rsync_command(
            files_from=list_path,
            source=source,
            dest=str(dest),
            ssh_command=ssh_command,
            rsync_bin=rsync_bin,
        )
        logger.info(
            "Rsyncing %s missing asset object(s) from %s.",
            len(missing),
            source,
        )
        run(cmd, check=True)
        for digest in missing:
            if _promote_staged_object(digest, dest, cache_root):
                written.append(digest)
    return written


def _normalize_digest(digest: str) -> str:
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ValueError(f"Invalid content digest for asset rsync: {digest!r}")
    return digest.lower()


def _ensure_trailing_slash(path: str) -> str:
    return path if path.endswith("/") else f"{path}/"


def _promote_staged_object(
    digest: str,
    staging_root: Path,
    cache_root: Optional[Union[str, Path]],
) -> bool:
    staged = staging_root / object_relative_path(digest)
    if not staged.exists():
        logger.warning("Rsync did not produce object %s.", digest)
        return False

    actual = sha256_directory(staged) if staged.is_dir() else sha256_file(staged)
    if actual != digest:
        logger.warning(
            "Discarding rsynced object %s due to digest mismatch (got %s).",
            digest,
            actual,
        )
        if staged.is_dir():
            shutil.rmtree(staged, ignore_errors=True)
        else:
            staged.unlink(missing_ok=True)
        return False

    dest = object_cache_path(digest, cache_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return False
    os.replace(str(staged), str(dest))
    _make_read_only(dest)
    return True
