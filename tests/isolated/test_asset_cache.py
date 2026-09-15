"""Unit tests for the persistent local asset export cache.

These tests exercise the public API of :mod:`psynet.export.asset_cache`
without requiring a running PsyNet experiment or database connection.
"""

import hashlib
import os
import shutil
import stat

import pytest

from psynet.export.asset_cache import (
    cache_size_bytes,
    default_cache_root,
    ensure_object_in_cache,
    link_or_copy,
    list_cached_objects,
    object_cache_path,
    prune_cached_objects,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cache_root(tmp_path):
    """An isolated temporary cache root for each test."""
    return tmp_path / "cache"


@pytest.fixture()
def sample_file(tmp_path):
    """A small sample text file with a known digest."""
    p = tmp_path / "sample.txt"
    p.write_bytes(b"hello cache")
    digest = hashlib.sha256(b"hello cache").hexdigest()
    return p, digest


# ---------------------------------------------------------------------------
# object_cache_path
# ---------------------------------------------------------------------------


def test_object_cache_path_structure(cache_root):
    path = object_cache_path("abc123", cache_root)
    assert path == cache_root / "objects" / "sha256" / "abc123"


def test_default_cache_root_is_under_home():
    root = default_cache_root()
    assert str(root).startswith(os.path.expanduser("~"))
    assert "psynet-data" in str(root)


# ---------------------------------------------------------------------------
# ensure_object_in_cache — file
# ---------------------------------------------------------------------------


def test_ensure_object_in_cache_file_basic(cache_root, sample_file):
    src, digest = sample_file

    def fetch_fn(dest):
        shutil.copy2(str(src), dest)

    cache_path = ensure_object_in_cache(digest, fetch_fn, cache_root=cache_root)

    assert cache_path.exists()
    assert cache_path == object_cache_path(digest, cache_root)
    assert cache_path.read_bytes() == b"hello cache"
    assert not cache_path.stat().st_mode & stat.S_IWUSR


def test_ensure_object_in_cache_file_idempotent(cache_root, sample_file):
    """Calling ensure twice should not re-fetch (fetch_fn not called again)."""
    src, digest = sample_file
    call_count = {"n": 0}

    def fetch_fn(dest):
        call_count["n"] += 1
        shutil.copy2(str(src), dest)

    ensure_object_in_cache(digest, fetch_fn, cache_root=cache_root)
    ensure_object_in_cache(digest, fetch_fn, cache_root=cache_root)

    assert call_count["n"] == 1


def test_ensure_object_in_cache_replaces_a_corrupted_writable_entry(
    cache_root, sample_file
):
    src, digest = sample_file
    cache_path = ensure_object_in_cache(
        digest,
        lambda dest: shutil.copy2(str(src), dest),
        cache_root=cache_root,
    )
    cache_path.chmod(cache_path.stat().st_mode | stat.S_IWUSR)
    cache_path.write_bytes(b"corrupted")

    ensure_object_in_cache(
        digest,
        lambda dest: shutil.copy2(str(src), dest),
        cache_root=cache_root,
    )

    assert cache_path.read_bytes() == b"hello cache"
    assert not cache_path.stat().st_mode & stat.S_IWUSR


def test_ensure_object_in_cache_wrong_digest_raises(cache_root, tmp_path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"actual content")
    wrong_digest = "0" * 64

    with pytest.raises(ValueError, match="Digest mismatch"):
        ensure_object_in_cache(
            wrong_digest,
            lambda dest: shutil.copy2(str(p), dest),
            cache_root=cache_root,
        )

    # Temp file must be cleaned up on failure.
    objects_dir = cache_root / "objects" / "sha256"
    partials = list(objects_dir.glob(".partial-*")) if objects_dir.exists() else []
    assert not partials, "Partial files were not cleaned up"


# ---------------------------------------------------------------------------
# ensure_object_in_cache — folder
# ---------------------------------------------------------------------------


def test_ensure_object_in_cache_folder(cache_root, tmp_path):
    from psynet.utils import sha256_directory

    src_dir = tmp_path / "src_folder"
    src_dir.mkdir()
    (src_dir / "a.txt").write_bytes(b"file a")
    (src_dir / "b.txt").write_bytes(b"file b")
    digest = sha256_directory(src_dir)

    def fetch_fn(dest):
        shutil.copytree(str(src_dir), dest)

    cache_path = ensure_object_in_cache(
        digest, fetch_fn, cache_root=cache_root, is_folder=True
    )

    assert cache_path.is_dir()
    assert (cache_path / "a.txt").read_bytes() == b"file a"
    assert (cache_path / "b.txt").read_bytes() == b"file b"


def test_ensure_object_in_cache_folder_wrong_digest_raises(cache_root, tmp_path):
    src_dir = tmp_path / "src_folder"
    src_dir.mkdir()
    (src_dir / "x.txt").write_bytes(b"something")
    wrong_digest = "a" * 64

    with pytest.raises(ValueError, match="Digest mismatch"):
        ensure_object_in_cache(
            wrong_digest,
            lambda dest: shutil.copytree(str(src_dir), dest),
            cache_root=cache_root,
            is_folder=True,
        )

    # Temp directory must be cleaned up.
    objects_dir = cache_root / "objects" / "sha256"
    partials = list(objects_dir.glob(".partial-*")) if objects_dir.exists() else []
    assert not partials, "Partial directories were not cleaned up"


# ---------------------------------------------------------------------------
# link_or_copy
# ---------------------------------------------------------------------------


def test_link_or_copy_hardlink_same_inode(cache_root, sample_file):
    src, digest = sample_file
    dest = cache_root / "linked_file.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)

    link_or_copy(src, dest)

    assert dest.exists()
    assert dest.read_bytes() == b"hello cache"
    # On the same filesystem, hardlink shares the inode.
    src_ino = src.stat().st_ino
    dest_ino = dest.stat().st_ino
    assert src_ino == dest_ino, (
        "Expected a hardlink (same inode) on the same filesystem"
    )
    assert not dest.stat().st_mode & stat.S_IWUSR


def test_link_or_copy_file_creates_parent(tmp_path):
    src = tmp_path / "source.txt"
    src.write_bytes(b"data")
    dest = tmp_path / "deep" / "nested" / "dest.txt"

    link_or_copy(src, dest)

    assert dest.read_bytes() == b"data"


def test_link_or_copy_folder(tmp_path):
    src = tmp_path / "src_dir"
    src.mkdir()
    (src / "file.txt").write_bytes(b"content")
    dest = tmp_path / "dest_dir"

    link_or_copy(src, dest, is_folder=True)

    assert dest.is_dir()
    assert (dest / "file.txt").read_bytes() == b"content"


# ---------------------------------------------------------------------------
# list_cached_objects / prune_cached_objects / cache_size_bytes
# ---------------------------------------------------------------------------


def test_list_cached_objects_empty(cache_root):
    assert list_cached_objects(cache_root) == []


def test_list_cached_objects_populated(cache_root, tmp_path):
    digests = ["aaa" + "0" * 61, "bbb" + "0" * 61]
    for d in digests:
        p = object_cache_path(d, cache_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    found = list_cached_objects(cache_root)
    assert found == sorted(digests)


def test_prune_cached_objects_all(cache_root, tmp_path):
    digests = ["aaa" + "0" * 61, "bbb" + "0" * 61]
    for d in digests:
        p = object_cache_path(d, cache_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    removed = prune_cached_objects(cache_root=cache_root)
    assert set(removed) == set(digests)
    assert list_cached_objects(cache_root) == []


def test_prune_cached_objects_keep_subset(cache_root):
    digests = ["aaa" + "0" * 61, "bbb" + "0" * 61, "ccc" + "0" * 61]
    for d in digests:
        p = object_cache_path(d, cache_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    keep = [digests[0]]
    removed = prune_cached_objects(digests_to_keep=keep, cache_root=cache_root)

    assert set(removed) == {digests[1], digests[2]}
    remaining = list_cached_objects(cache_root)
    assert remaining == [digests[0]]


def test_cache_size_bytes_empty(cache_root):
    assert cache_size_bytes(cache_root) == 0


def test_cache_size_bytes_populated(cache_root):
    p = object_cache_path("d" * 64, cache_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"1234567890")  # 10 bytes

    assert cache_size_bytes(cache_root) == 10


# ---------------------------------------------------------------------------
# Cache + export integration: second call reuses cache (same inode)
# ---------------------------------------------------------------------------


def test_second_export_reuses_cache(cache_root, tmp_path):
    """Exporting the same digest twice produces hardlinked files on the same FS."""
    content = b"reuse me"
    digest = hashlib.sha256(content).hexdigest()
    src = tmp_path / "original.bin"
    src.write_bytes(content)

    export1 = tmp_path / "export1" / "objects" / "sha256" / digest
    export2 = tmp_path / "export2" / "objects" / "sha256" / digest

    # First export: populate cache and link to export1.
    cache_path = ensure_object_in_cache(
        digest,
        lambda dest: shutil.copy2(str(src), dest),
        cache_root=cache_root,
    )
    export1.parent.mkdir(parents=True, exist_ok=True)
    link_or_copy(cache_path, export1)

    # Second export: cache hit, link to export2.
    fetch_count = {"n": 0}

    def counting_fetch(dest):
        fetch_count["n"] += 1
        shutil.copy2(str(src), dest)

    cache_path2 = ensure_object_in_cache(digest, counting_fetch, cache_root=cache_root)
    export2.parent.mkdir(parents=True, exist_ok=True)
    link_or_copy(cache_path2, export2)

    assert fetch_count["n"] == 0, "Second export should not fetch from storage"
    # All three paths (cache, export1, export2) share the same inode.
    inodes = {export1.stat().st_ino, export2.stat().st_ino, cache_path.stat().st_ino}
    assert len(inodes) == 1, f"Expected single shared inode; got {inodes}"


# ---------------------------------------------------------------------------
# Soft size warning
# ---------------------------------------------------------------------------


def test_soft_limit_bytes_default():
    from psynet.export.asset_cache import soft_limit_bytes

    assert soft_limit_bytes() == 50 * 1024**3


def test_soft_limit_bytes_env_override(monkeypatch):
    from psynet.export.asset_cache import soft_limit_bytes

    monkeypatch.setenv("PSYNET_ASSET_CACHE_SOFT_LIMIT_BYTES", "12345")
    assert soft_limit_bytes() == 12345


def test_warn_if_cache_oversized_silent_when_under_limit(cache_root, caplog):
    from psynet.export.asset_cache import warn_if_cache_oversized

    p = object_cache_path("e" * 64, cache_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"tiny")

    with caplog.at_level("WARNING"):
        assert warn_if_cache_oversized(cache_root, limit_bytes=1000) is None
    assert "soft limit" not in caplog.text


def test_warn_if_cache_oversized_when_over_limit(cache_root, caplog):
    from psynet.export.asset_cache import warn_if_cache_oversized

    p = object_cache_path("f" * 64, cache_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"0123456789")  # 10 bytes

    with caplog.at_level("WARNING"):
        message = warn_if_cache_oversized(cache_root, limit_bytes=5)
    assert message is not None
    assert "soft limit" in message
    assert "psynet assets cache prune --all" in message
    assert "soft limit" in caplog.text


def test_warn_if_cache_oversized_disabled_when_limit_nonpositive(cache_root):
    from psynet.export.asset_cache import warn_if_cache_oversized

    p = object_cache_path("a" * 64, cache_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"data")
    assert warn_if_cache_oversized(cache_root, limit_bytes=0) is None
