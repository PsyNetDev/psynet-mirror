"""Shared helpers for export transport and rsync tests."""

from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
import warnings
import zipfile
from pathlib import Path

from psynet.utils import sha256_directory


def write_zip_with_duplicate_member(path: Path, members: list[tuple[str, str]]) -> Path:
    """Write a zip that intentionally repeats a member name.

    ``ZipFile.writestr`` warns on duplicates, and CI runs tests with
    ``-Werror``, so the warning is suppressed while building this
    deliberately malformed fixture.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:")
        with zipfile.ZipFile(path, "w") as handle:
            for name, payload in members:
                handle.writestr(name, payload)
    return path


def write_remote_object(root: Path, payload: bytes) -> str:
    """Write a content-addressed object and return its digest."""
    digest = hashlib.sha256(payload).hexdigest()
    dest = root / "objects" / "sha256" / digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return digest


def write_remote_folder(root: Path, files: dict[str, bytes]) -> str:
    """Write a content-addressed folder object and return its digest."""
    staging = root / "_src"
    staging.mkdir(parents=True)
    for name, payload in files.items():
        (staging / name).write_bytes(payload)
    digest = sha256_directory(staging)
    dest = root / "objects" / "sha256" / digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging, dest)
    shutil.rmtree(staging)
    return digest


def rsync_files_from_double(remote_root: Path, calls: list | None = None):
    """Copy ``--files-from`` paths without requiring an ``rsync`` binary."""

    def run(cmd, check=False, **kwargs):
        if calls is not None:
            calls.append(cmd)
        files_from = Path(cmd[cmd.index("--files-from") + 1])
        dest = Path(str(cmd[-1]).rstrip("/"))
        for rel in files_from.read_text().splitlines():
            if not rel:
                continue
            src = remote_root / rel
            if not src.exists():
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
        result = subprocess.CompletedProcess(cmd, 0)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd)
        return result

    return run


def write_asset_manifest(export_dir: Path, rows: list[dict]) -> None:
    """Write a minimal ``assets/manifest.csv`` for hydration tests."""
    assets = export_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "type",
        "export_path",
        "sha256_contents",
        "is_folder",
        "storage",
    ]
    with (assets / "manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
