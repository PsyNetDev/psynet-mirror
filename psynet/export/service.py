"""Server-side export operations: build, archive, store, and serve.

Why this module exists
----------------------
Export used to be orchestrated by Click commands that re-invoked each other,
with the dashboard route calling the CLI through a synthetic Click context.
That made it impossible to reason about which side of the wire did the work,
and it coupled a Flask route to command-line argument parsing.

Everything here runs *inside the deployed experiment*, against the live
database, and never touches the experimenter's machine. The client-side
counterpart is :mod:`psynet.export.client`.

Design constraints
------------------
* Each operation does one thing: :func:`build_export_tree` produces the
  canonical export product, :func:`build_export_archive` zips it,
  :func:`store_latest_archive` persists it as the deployment's single latest
  artifact. Callers compose these explicitly, so a download no longer stores
  an artifact as a side effect and a backup no longer builds an unused Flask
  response.
* ``EXPORT_FORMAT_VERSION`` in :mod:`psynet.export.paths` is the contract
  between server and client. Bump it only for changes that an older client
  cannot read; it is recorded in ``manifest.json`` so clients can refuse an
  archive they do not understand.
* Nothing here imports Click. Operations raise ordinary exceptions and let the
  caller decide how to report them.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from psynet.utils import get_logger, make_parents

from .paths import EXPORT_ZIP_NAME, dashboard_export_zip_path

logger = get_logger()

#: Asset selections accepted by :func:`build_export_tree`.
ASSET_MODES = ("none", "collected")

#: Error when a caller still requests the removed ``all`` selection.
#: Shared by the CLI (``--assets``) and dashboard routes (``?assets=``).
REMOVED_ASSETS_ALL = (
    "The asset selection 'all' has been removed. Use collected (the default) "
    "for files deposited during the run, such as recordings. Copy cached "
    "stimuli from the experiment directory or storage if you need them for "
    "supplementary materials. On-demand assets are generated live and are "
    "not written into the archive."
)


def validate_asset_mode(assets: str) -> str:
    """Return ``assets`` when it is a supported export selection.

    Used by ``psynet export --assets`` and by dashboard download/trigger
    query parameters (``?assets=``). Keep the message caller-agnostic.

    Raises
    ------
    ValueError
        If ``assets`` is ``all`` or another unsupported value.
    """
    if assets == "all":
        raise ValueError(REMOVED_ASSETS_ALL)
    if assets not in ASSET_MODES:
        raise ValueError(
            f"Asset selection must be one of {', '.join(ASSET_MODES)}; got {assets!r}."
        )
    return assets


def build_export_tree(
    export_path: str,
    *,
    assets: str = "collected",
    server: Optional[str] = None,
    local: bool = True,
    manifest_only_assets: bool = False,
) -> str:
    """Build the canonical export product in ``export_path`` from the live database.

    Parameters
    ----------
    export_path :
        Directory to populate. Created if missing.
    assets :
        One of ``none`` or ``collected``.
    server :
        SSH server name, when asset bytes must be fetched from a remote host.
    local :
        Whether asset bytes are available on this machine.
    manifest_only_assets :
        Write ``assets/manifest.csv`` describing the selected assets without
        copying any bytes. Used by the incremental SSH transport, which fetches
        the bytes itself.

    Returns
    -------
    str
        ``export_path``.
    """
    assets = validate_asset_mode(assets)

    from .database import export_database_snapshot

    os.makedirs(export_path, exist_ok=True)
    export_database_snapshot(export_path)
    write_basic_data(export_path)

    if assets != "none":
        export_selected_assets(
            export_path,
            server=server,
            local=local,
            manifest_only=manifest_only_assets,
        )

    return export_path


def build_export_archive(export_dir: str, zip_path: Optional[str] = None) -> str:
    """Zip an export tree, writing ``export.zip`` beside it by default."""
    from .zip_utils import build_zip_from_dir

    if zip_path is None:
        zip_path = dashboard_export_zip_path(export_dir)
    return build_zip_from_dir(export_dir, zip_path)


def store_latest_archive(zip_path: str) -> Optional[str]:
    """Store ``zip_path`` as the deployment's single latest export artifact.

    Storage failures are logged rather than raised, because a download or
    scheduled backup should not fail just because remote storage is
    unavailable.

    Returns
    -------
    str or None
        The artifact URL, or ``None`` if storage was unavailable.
    """
    from psynet.experiment import get_experiment

    experiment = get_experiment()
    storage = experiment.artifact_storage
    if storage is None:
        logger.warning(
            "No artifact storage is configured, so the export was not stored remotely."
        )
        return None
    try:
        storage.upload_export(zip_path, deployment_id=experiment.deployment_id)
    except Exception:
        logger.error(
            "Failed to store the export artifact for deployment %s.",
            experiment.deployment_id,
            exc_info=True,
        )
        return None

    url = experiment.get_artifact_url(experiment.deployment_id, EXPORT_ZIP_NAME)
    try:
        experiment.notifier.notify(
            "A fresh data export has been created, it can be accessed "
            f"{experiment.notifier.url('here', url)}."
        )
    except Exception:
        logger.warning("Could not send the export notification.", exc_info=True)
    return url


def export_selected_assets(
    export_path: str,
    *,
    server: Optional[str] = None,
    local: bool = True,
    manifest_only: bool = False,
) -> str:
    """Export collected assets into ``export_path/assets``.

    Collected assets are managed files deposited during this deployment.
    Treat exported media as potentially identifying: identifier
    separation applies to database tables only.
    """
    from psynet.data import export_assets as _export_assets

    from .asset_cache import warn_if_cache_oversized

    asset_path = os.path.join(export_path, "assets")
    logger.info("Exporting assets to %s.", asset_path)
    _export_assets(
        asset_path,
        server=server,
        local=local,
        manifest_only=manifest_only,
    )
    if not manifest_only:
        oversized_message = warn_if_cache_oversized()
        if oversized_message:
            logger.warning(oversized_message)
    return asset_path


###############
# basic data  #
###############


def write_basic_data(export_path: str) -> None:
    """Write optional experiment-defined basic data beside the database snapshot."""
    from psynet.experiment import get_experiment

    data = get_experiment().get_basic_data(context="export")
    if data is None:
        return
    if _is_dataframe_dict(data):
        _write_basic_dataframes(export_path, data)
    else:
        _write_basic_data_json(export_path, data)


def _write_basic_dataframes(export_path, data):
    basic_data_dir = os.path.join(export_path, "basic_data")
    os.makedirs(basic_data_dir, exist_ok=True)
    filename_counts = {}
    used_filenames = set()
    for key, dataframe in data.items():
        filename = _make_basic_data_filename(key, filename_counts, used_filenames)
        dataframe.to_csv(os.path.join(basic_data_dir, f"{filename}.csv"), index=False)


def _write_basic_data_json(export_path, data):
    basic_data_path = os.path.join(export_path, "basic_data.json")
    with open(make_parents(basic_data_path), "w") as handle:
        json.dump(data, handle, indent=2)


def _make_basic_data_filename(key, counts, used_filenames):
    """Allocate a unique CSV-safe filename stem for one basic-data key.

    Parameters
    ----------
    key : Any
        Original basic-data key from the export payload.
    counts : dict[str, int]
        Per-sanitized-key counters used to generate numeric suffixes.
    used_filenames : set[str]
        Case-folded filename stems already reserved in this export run.

    Returns
    -------
    str
        A unique filename stem (without extension).
    """
    sanitized = _sanitize_basic_data_key(key)
    counts[sanitized] = counts.get(sanitized, 0)

    while True:
        counts[sanitized] += 1
        count = counts[sanitized]
        filename = sanitized if count == 1 else f"{sanitized}_{count}"
        # Reserve names case-insensitively to avoid collisions on
        # case-insensitive filesystems (e.g., default macOS/Windows).
        reserved_name = filename.casefold()
        if reserved_name not in used_filenames:
            used_filenames.add(reserved_name)
            return filename


def _sanitize_basic_data_key(key):
    filename = str(key).strip()
    filename = re.sub(r"[\\/]+", "_", filename)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    filename = filename.strip("._")
    return filename or "data"


def _is_dataframe_dict(data):
    if not isinstance(data, dict) or not data:
        return False
    try:
        import pandas as pd
    except ImportError:
        return False
    return all(isinstance(value, pd.DataFrame) for value in data.values())
