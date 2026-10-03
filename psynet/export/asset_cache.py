"""Persistent local cache for content-addressed asset objects.

The cache lives at ``~/psynet-data/cache/assets`` and mirrors the
``objects/sha256/<digest>`` layout used in export archives.  During each
export run, managed assets whose SHA-256 digest is already known are
served from the cache with a hardlink (or copy on different filesystems)
rather than re-fetched from remote storage.  Only objects that are absent
from the cache are fetched, verified, and placed atomically.  Read-only
cache hits are trusted without re-hashing; writable entries are re-hashed
before reuse.  If cache files were edited while marked read-only, prune
the cache (``psynet assets cache prune --all``).

Layout
------
::

    ~/psynet-data/cache/assets/
    └── objects/
        └── sha256/
            └── <hex-digest>          # file or directory

Thread/process safety
---------------------
``ensure_object_in_cache`` writes to a temporary sibling path on the same
filesystem as the final cache entry, then renames atomically.  A
concurrent writer for the same digest is tolerated: the loser silently
discards its temp copy if the target already exists after the rename.

Maintainer notes
----------------
This module avoids direct PsyNet database / SQLAlchemy model imports so
its cache helpers can be unit-tested without a running experiment. It
does import hashing helpers from ``psynet.utils``.
"""

import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Union

from psynet.utils import sha256_directory, sha256_file

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT: Path = Path("~/psynet-data/cache/assets").expanduser()

# Soft size warning only: exports never fail because of this limit.
# Override with PSYNET_ASSET_CACHE_SOFT_LIMIT_BYTES (integer byte count).
_DEFAULT_SOFT_LIMIT_BYTES = 50 * 1024**3  # 50 GiB
_SOFT_LIMIT_ENV = "PSYNET_ASSET_CACHE_SOFT_LIMIT_BYTES"


def default_cache_root() -> Path:
    """Return the default asset cache root (``~/psynet-data/cache/assets``)."""
    return _DEFAULT_CACHE_ROOT


def object_cache_path(
    digest: str,
    cache_root: Optional[Union[str, Path]] = None,
) -> Path:
    """Return the absolute path where ``digest`` lives in the cache.

    Parameters
    ----------
    digest :
        SHA-256 hex digest string.
    cache_root :
        Override the default cache root.  Expanded with
        :func:`os.path.expanduser` when provided as a string.
    """
    root = _resolve_root(cache_root)
    return root / "objects" / "sha256" / digest


def ensure_object_in_cache(
    digest: str,
    fetch_fn: Callable[[str], None],
    cache_root: Optional[Union[str, Path]] = None,
    is_folder: bool = False,
) -> Path:
    """Guarantee that ``digest`` is present in the cache, fetching if absent.

    The fetch is done into a temporary sibling path on the same filesystem as
    the final cache entry so the rename is always atomic.  A
    ``ValueError`` is raised if the fetched content does not match
    ``digest``.

    Parameters
    ----------
    digest :
        Expected SHA-256 hex digest.
    fetch_fn :
        Callable that receives a destination path string and must write
        the object's bytes to that path (file) or populate that directory
        (folder).  Called only when the object is absent from the cache.
    cache_root :
        Override the default cache root.
    is_folder :
        ``True`` when the object is a directory tree rather than a file.

    Returns
    -------
    Path
        Absolute path to the cached object (file or directory).

    Raises
    ------
    ValueError
        When the fetched content's SHA-256 digest differs from ``digest``.
    """
    cache_path = object_cache_path(digest, cache_root)
    if _cached_object_is_valid(digest, cache_path):
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if is_folder:
        _fetch_folder_to_cache(digest, fetch_fn, cache_path)
    else:
        _fetch_file_to_cache(digest, fetch_fn, cache_path)

    _make_read_only(cache_path)
    return cache_path


def link_or_copy(
    src: Union[str, Path],
    dest: Union[str, Path],
    is_folder: bool = False,
) -> None:
    """Link ``src`` to ``dest``, falling back to copy on a different filesystem.

    A hardlink shares the inode so the cache and the export refer to the
    same on-disk bytes without duplication.  The fallback is
    :func:`shutil.copy2` for files and :func:`shutil.copytree` for
    directories.

    Parameters
    ----------
    src :
        Source path (must exist).
    dest :
        Destination path (must not exist; parent directory is created
        automatically).
    is_folder :
        ``True`` when ``src`` is a directory.
    """
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _make_read_only(src)

    if is_folder:
        shutil.copytree(str(src), str(dest))
        return

    try:
        os.link(str(src), str(dest))
    except OSError:
        shutil.copy2(str(src), str(dest))


def list_cached_objects(
    cache_root: Optional[Union[str, Path]] = None,
) -> List[str]:
    """Return a sorted list of SHA-256 digests present in the cache.

    Parameters
    ----------
    cache_root :
        Override the default cache root.
    """
    root = _resolve_root(cache_root)
    objects_dir = root / "objects" / "sha256"
    if not objects_dir.exists():
        return []
    return sorted(
        entry.name for entry in objects_dir.iterdir() if not entry.name.startswith(".")
    )


def prune_cached_objects(
    digests_to_keep: Optional[List[str]] = None,
    cache_root: Optional[Union[str, Path]] = None,
) -> List[str]:
    """Remove cached objects that are not in ``digests_to_keep``.

    Parameters
    ----------
    digests_to_keep :
        When provided, only objects whose digest is **not** in this list
        are deleted.  When ``None`` (the default), every cached object is
        removed.
    cache_root :
        Override the default cache root.

    Returns
    -------
    list of str
        Sorted list of digests that were removed.
    """
    root = _resolve_root(cache_root)
    objects_dir = root / "objects" / "sha256"
    if not objects_dir.exists():
        return []

    keep: set = set(digests_to_keep) if digests_to_keep is not None else set()
    removed: List[str] = []

    for entry in objects_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.name not in keep:
            if entry.is_dir():
                shutil.rmtree(str(entry))
            else:
                entry.unlink()
            removed.append(entry.name)
            logger.info("Pruned cached asset object: %s", entry.name)

    return sorted(removed)


def cache_size_bytes(cache_root: Optional[Union[str, Path]] = None) -> int:
    """Return the total byte count of all objects in the cache.

    Parameters
    ----------
    cache_root :
        Override the default cache root.
    """
    root = _resolve_root(cache_root)
    objects_dir = root / "objects" / "sha256"
    if not objects_dir.exists():
        return 0

    total = 0
    for entry in objects_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_file():
            total += entry.stat().st_size
        elif entry.is_dir():
            for p in entry.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
    return total


def soft_limit_bytes() -> int:
    """Return the soft cache size limit in bytes.

    Defaults to 50 GiB. Override with the environment variable
    ``PSYNET_ASSET_CACHE_SOFT_LIMIT_BYTES``.
    """
    raw = os.environ.get(_SOFT_LIMIT_ENV)
    if raw is None or raw == "":
        return _DEFAULT_SOFT_LIMIT_BYTES
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{_SOFT_LIMIT_ENV} must be an integer number of bytes, got {raw!r}"
        ) from exc


def warn_if_cache_oversized(
    cache_root: Optional[Union[str, Path]] = None,
    limit_bytes: Optional[int] = None,
) -> Optional[str]:
    """Warn when the cache exceeds the soft size limit.

    This never blocks exports or deletes objects. A large single experiment
    may legitimately exceed the limit; the warning only nudges the user to
    run ``psynet assets cache prune --all`` when convenient.

    Parameters
    ----------
    cache_root :
        Override the default cache root.
    limit_bytes :
        Soft limit in bytes. Defaults to :func:`soft_limit_bytes`.

    Returns
    -------
    str or None
        The warning message when oversized, otherwise ``None``.
    """
    from psynet.utils import format_bytes

    if limit_bytes is None:
        limit_bytes = soft_limit_bytes()
    if limit_bytes <= 0:
        return None

    size = cache_size_bytes(cache_root)
    if size <= limit_bytes:
        return None

    root = _resolve_root(cache_root)
    message = (
        f"Asset export cache at {root} is {format_bytes(size)} "
        f"(soft limit {format_bytes(limit_bytes)}). "
        "Exports still succeed; run `psynet assets cache prune --all` "
        "when you no longer need cached objects."
    )
    logger.warning(message)
    return message


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_root(cache_root: Optional[Union[str, Path]]) -> Path:
    """Resolve a cache root argument to an absolute Path."""
    if cache_root is None:
        return default_cache_root()
    return Path(os.path.expanduser(str(cache_root)))


def _cached_object_is_valid(digest: str, path: Path) -> bool:
    """Return whether a cache entry exists and still matches its content address.

    Newly written cache entries are read-only. Existing writable entries (from
    older PsyNet versions, or because a hard-linked export was made writable)
    are hashed once before being trusted and returned to read-only mode.
    """
    if not path.exists():
        return False
    if not _has_write_bits(path):
        return True

    actual = sha256_directory(path) if path.is_dir() else sha256_file(path)
    if actual == digest:
        _make_read_only(path)
        return True

    logger.warning("Discarding corrupted cached asset object %s.", digest)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return False


def _has_write_bits(path: Path) -> bool:
    return bool(path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _make_read_only(path: Path) -> None:
    """Remove write permissions from a cached object and its contents."""
    if path.is_dir():
        for child in path.rglob("*"):
            child.chmod(child.stat().st_mode & ~0o222)
    path.chmod(path.stat().st_mode & ~0o222)


def _fetch_file_to_cache(
    digest: str,
    fetch_fn: Callable[[str], None],
    cache_path: Path,
) -> None:
    """Fetch a file object into ``cache_path`` via a verified atomic write."""
    parent = cache_path.parent
    # Write to a temp file on the same filesystem to ensure atomic rename.
    fd, tmp_str = tempfile.mkstemp(dir=parent, prefix=".partial-")
    tmp_path = Path(tmp_str)
    try:
        os.close(fd)
        # Remove the placeholder so fetch_fn can write a fresh file.
        tmp_path.unlink()
        fetch_fn(str(tmp_path))
        actual = sha256_file(tmp_path)
        if actual != digest:
            raise ValueError(
                f"Digest mismatch for cached asset: expected {digest!r}, got {actual!r}"
            )
        try:
            os.replace(str(tmp_path), str(cache_path))
        except OSError:
            if cache_path.exists():
                # Race: another process won the rename.
                tmp_path.unlink(missing_ok=True)
            else:
                raise
        _make_read_only(cache_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _fetch_folder_to_cache(
    digest: str,
    fetch_fn: Callable[[str], None],
    cache_path: Path,
) -> None:
    """Fetch a folder object into ``cache_path`` via a verified atomic move.

    ``fetch_fn`` is called with a path that does **not** yet exist; the
    function must create the directory and populate it.  This matches the
    convention used by :func:`shutil.copytree` and PsyNet's own
    ``Asset.export()`` for folder assets.
    """
    parent = cache_path.parent
    # Use a unique sibling path on the same filesystem (no pre-creation so
    # fetch_fn can create the directory itself via shutil.copytree, etc.).
    tmp_dir = parent / f".partial-{os.urandom(8).hex()}"
    try:
        fetch_fn(str(tmp_dir))
        actual = sha256_directory(tmp_dir)
        if actual != digest:
            raise ValueError(
                f"Digest mismatch for cached asset folder: expected {digest!r}, got {actual!r}"
            )
        try:
            os.rename(str(tmp_dir), str(cache_path))
        except OSError:
            if cache_path.exists():
                # Race: another process won the rename.
                shutil.rmtree(str(tmp_dir), ignore_errors=True)
            else:
                raise
        _make_read_only(cache_path)
    except Exception:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
        raise
