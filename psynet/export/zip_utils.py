"""Compression-aware ZIP archive builder for PsyNet exports.

Dashboard downloads are full archives built directly from the export tree.
This module chooses ZIP_STORED for file types that are already compressed
(media, images, nested archives) and ZIP_DEFLATED for compressible text
formats (CSV, JSON, manifest files).  Avoiding redundant DEFLATE passes on
pre-compressed data cuts both CPU time and archive size overhead.

Maintainer notes
----------------
Add extensions to :data:`_STORED_EXTENSIONS` when a new media or container
format is introduced that is already internally compressed.  Keep this list
extension-only (lower-case, with leading dot) so :func:`_compression_for`
stays O(1) per file.
"""

from __future__ import annotations

import os
import zipfile

# File extensions whose content is already compressed; applying DEFLATE gains
# nothing and wastes CPU.  Includes common media, image, and archive types.
_STORED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Audio
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".flac",
        ".wav",  # PCM WAV rarely compresses well
        # Video
        ".mp4",
        ".webm",
        # Images (lossy/lossless compressed)
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".heic",
        ".heif",
        ".avif",
        # Archive / compressed container formats
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".zst",
        ".br",
    }
)


def _compression_for(arcname: str) -> int:
    """Return the appropriate zipfile compression constant for *arcname*.

    Returns :data:`zipfile.ZIP_STORED` for file types in
    :data:`_STORED_EXTENSIONS`, and for content-addressed object paths under
    ``objects/sha256/`` (which omit file extensions). Returns
    :data:`zipfile.ZIP_DEFLATED` for everything else.

    Parameters
    ----------
    arcname:
        The archive member name (or any path whose extension is meaningful).
    """
    normalized = arcname.replace("\\", "/")
    if "/objects/sha256/" in f"/{normalized}":
        return zipfile.ZIP_STORED
    ext = os.path.splitext(arcname)[1].lower()
    if ext in _STORED_EXTENSIONS:
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


def build_zip_from_dir(source_dir: str, zip_path: str) -> str:
    """Build a ZIP archive from *source_dir* into *zip_path*.

    The archive layout mirrors the contents of *source_dir* with paths
    relative to it — the same behaviour as
    ``shutil.make_archive(..., "zip", source_dir)`` — but each member is
    compressed with :func:`_compression_for` rather than always using
    DEFLATE.

    Parameters
    ----------
    source_dir:
        Root directory whose contents become the archive members.
    zip_path:
        Destination path for the ZIP file.  Created (or overwritten) by
        this function.  The parent directory must already exist.

    Returns
    -------
    str
        Absolute path to the created archive (same as *zip_path* resolved).
    """
    zip_path = os.path.abspath(zip_path)
    with zipfile.ZipFile(zip_path, "w", allowZip64=True) as zf:
        for dirpath, dirnames, filenames in os.walk(source_dir):
            dirnames.sort()
            for filename in sorted(filenames):
                full_path = os.path.join(dirpath, filename)
                arcname = os.path.relpath(full_path, source_dir)
                compression = _compression_for(arcname)
                zf.write(full_path, arcname, compress_type=compression)
    return zip_path
