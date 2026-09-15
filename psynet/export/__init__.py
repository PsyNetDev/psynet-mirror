"""Canonical PsyNet export: database tables, identifier sidecars, and analysis helpers.

The shareable export uses pseudonymous participant identifiers in
``database/*.csv``. Original recruiter identifiers are written beside that
directory in sidecar CSV files. This is identifier separation, not
anonymization.

Module map
----------
* :mod:`psynet.export.service` — what the deployed experiment does: build the
  export tree, archive it, store it, serve it.
* :mod:`psynet.export.client` — what the experimenter's machine does: preflight,
  choose a transport, stream, hydrate assets, publish atomically.
* :mod:`psynet.export.identity` — project identity and export-format checks made
  before any bytes move.
* :mod:`psynet.export.database`, :mod:`psynet.export.identifiers` — the
  canonical table snapshot and identifier separation.

Asset cache
-----------
:mod:`psynet.export.asset_cache` implements a persistent local cache at
``~/psynet-data/cache/assets`` that stores content-addressed objects in
``objects/sha256/<digest>``. Export archives materialize those bytes under
semantic ``export_path`` trees. SSH command-line exports fill missing cache
objects with one ``rsync --files-from`` from the remote LocalStorage tree. If
``rsync`` is unavailable, the export falls back to a complete server-built
archive; there is no per-asset SFTP fallback.
"""

from .analysis import (
    load_export_table,
    merge_participant_identifiers,
    unpack_json_column,
)
from .asset_cache import (
    cache_size_bytes,
    default_cache_root,
    ensure_object_in_cache,
    link_or_copy,
    list_cached_objects,
    object_cache_path,
    prune_cached_objects,
    soft_limit_bytes,
    warn_if_cache_oversized,
)
from .database import export_database_snapshot, write_identifier_sidecars
from .paths import DATABASE_DIRNAME, EXPORT_ZIP_NAME, resolve_database_dir
from .zip_utils import build_zip_from_dir

__all__ = [
    "DATABASE_DIRNAME",
    "EXPORT_ZIP_NAME",
    "build_zip_from_dir",
    "cache_size_bytes",
    "default_cache_root",
    "ensure_object_in_cache",
    "export_database_snapshot",
    "link_or_copy",
    "list_cached_objects",
    "load_export_table",
    "merge_participant_identifiers",
    "object_cache_path",
    "prune_cached_objects",
    "resolve_database_dir",
    "soft_limit_bytes",
    "unpack_json_column",
    "warn_if_cache_oversized",
    "write_identifier_sidecars",
]
