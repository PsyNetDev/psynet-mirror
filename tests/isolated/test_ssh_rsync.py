"""Tests for bulk SSH rsync of content-addressed asset objects."""

import hashlib
import shutil
import stat
import sys
from pathlib import Path

import pytest

from psynet.export.ssh_rsync import (
    RsyncRequiredError,
    build_rsync_command,
    default_ssh_command,
    emit_rsync_missing_warning,
    missing_object_digests,
    object_relative_path,
    prefetch_missing_objects,
    remote_assets_source,
    rsync_missing_warning_text,
)
from psynet.utils import sha256_directory, sha256_file

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from export_test_helpers import (  # noqa: E402
    rsync_files_from_double,
    write_remote_folder,
    write_remote_object,
)


@pytest.fixture()
def cache_root(tmp_path):
    return tmp_path / "cache"


@pytest.fixture()
def remote_assets(tmp_path):
    return tmp_path / "remote_assets"


def _write_object(root: Path, payload: bytes) -> str:
    return write_remote_object(root, payload)


def _make_rsync_double(remote_root: Path):
    """Copy ``--files-from`` paths without requiring an ``rsync`` binary."""
    return rsync_files_from_double(remote_root)


def _write_folder_object(root: Path, files: dict[str, bytes]) -> str:
    return write_remote_folder(root, files)


def test_object_relative_path_accepts_hex_digest():
    digest = "a" * 64
    assert object_relative_path(digest) == f"objects/sha256/{digest}"


def test_object_relative_path_rejects_traversal():
    with pytest.raises(ValueError, match="digest"):
        object_relative_path("../etc/passwd")
    with pytest.raises(ValueError, match="digest"):
        object_relative_path("objects/sha256/" + "a" * 64)


def test_missing_object_digests_skips_cached(cache_root, remote_assets):
    present = _write_object(cache_root, b"already here")
    absent = hashlib.sha256(b"not here").hexdigest()
    missing = missing_object_digests([present, absent, present], cache_root=cache_root)
    assert missing == [absent]


def test_missing_object_digests_discards_corrupted_writable_cache_entry(cache_root):
    digest = _write_object(cache_root, b"original")
    path = cache_root / "objects" / "sha256" / digest
    path.write_bytes(b"corrupted")

    assert missing_object_digests([digest], cache_root=cache_root) == [digest]
    assert not path.exists()


def test_missing_object_digests_marks_valid_cache_entry_read_only(cache_root):
    digest = _write_object(cache_root, b"original")
    path = cache_root / "objects" / "sha256" / digest

    assert missing_object_digests([digest], cache_root=cache_root) == []
    assert not path.stat().st_mode & stat.S_IWUSR


def test_remote_assets_source_uses_home_and_user():
    assert (
        remote_assets_source("example.com", "alice", "/home/alice")
        == "alice@example.com:/home/alice/psynet-data/assets/"
    )
    assert (
        remote_assets_source("example.com", None, "/home/alice")
        == "example.com:/home/alice/psynet-data/assets/"
    )


def test_default_ssh_command_includes_identity_and_batch_mode(tmp_path):
    pem = tmp_path / "key.pem"
    pem.write_text("dummy")
    cmd = default_ssh_command(pem)
    assert cmd[0] == "ssh"
    assert "-i" in cmd
    assert str(pem) in cmd
    assert "BatchMode=yes" in cmd
    assert "IdentitiesOnly=yes" in cmd


def test_build_rsync_command_uses_files_from_and_ssh():
    cmd = build_rsync_command(
        files_from="/tmp/list.txt",
        source="alice@host:/home/alice/psynet-data/assets/",
        dest="/tmp/cache/",
        ssh_command=["ssh", "-i", "/tmp/key.pem", "-o", "BatchMode=yes"],
    )
    assert cmd[0] == "rsync"
    assert "-r" in cmd
    assert "--files-from" in cmd
    assert cmd[cmd.index("--files-from") + 1] == "/tmp/list.txt"
    assert "-e" in cmd
    assert cmd[-2].endswith("/")
    assert cmd[-1].endswith("/")


def test_prefetch_missing_objects_rsyncs_only_absent_files(cache_root, remote_assets):
    cached = _write_object(cache_root, b"cached-bytes")
    missing = _write_object(remote_assets, b"remote-bytes")
    extra_remote = _write_object(remote_assets, b"should-not-copy")

    written = prefetch_missing_objects(
        [cached, missing],
        source=str(remote_assets),
        cache_root=cache_root,
        run=_make_rsync_double(remote_assets),
    )

    assert written == [missing]
    cached_path = cache_root / "objects" / "sha256" / cached
    missing_path = cache_root / "objects" / "sha256" / missing
    extra_path = cache_root / "objects" / "sha256" / extra_remote
    assert cached_path.read_bytes() == b"cached-bytes"
    assert missing_path.read_bytes() == b"remote-bytes"
    assert not extra_path.exists()
    assert sha256_file(missing_path) == missing


def test_prefetch_missing_objects_copies_folder_objects(cache_root, remote_assets):
    digest = _write_folder_object(remote_assets, {"a.txt": b"alpha", "b.txt": b"beta"})

    written = prefetch_missing_objects(
        [digest],
        source=str(remote_assets),
        cache_root=cache_root,
        run=_make_rsync_double(remote_assets),
    )

    assert written == [digest]
    dest = cache_root / "objects" / "sha256" / digest
    assert dest.is_dir()
    assert (dest / "a.txt").read_bytes() == b"alpha"
    assert (dest / "b.txt").read_bytes() == b"beta"
    assert sha256_directory(dest) == digest


def test_prefetch_missing_objects_is_noop_when_cache_complete(
    cache_root, remote_assets
):
    digest = _write_object(cache_root, b"done")
    calls = []

    def tracking_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError("rsync should not run when every object is cached")

    written = prefetch_missing_objects(
        [digest],
        source=str(remote_assets),
        cache_root=cache_root,
        run=tracking_run,
    )
    assert written == []
    assert calls == []


def test_prefetch_rejects_mismatched_bytes(cache_root, remote_assets):
    digest = "0" * 64
    dest = remote_assets / "objects" / "sha256" / digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"not the advertised digest")

    written = prefetch_missing_objects(
        [digest],
        source=str(remote_assets),
        cache_root=cache_root,
        run=_make_rsync_double(remote_assets),
    )

    assert written == []
    assert not (cache_root / "objects" / "sha256" / digest).exists()


def test_prefetch_invokes_rsync_once_with_all_missing_paths(cache_root, remote_assets):
    first = _write_object(remote_assets, b"one")
    second = _write_object(remote_assets, b"two")
    recorded = []
    listed = []
    fake = _make_rsync_double(remote_assets)

    def wrapping_run(cmd, *args, **kwargs):
        recorded.append(list(cmd))
        files_from = Path(cmd[cmd.index("--files-from") + 1])
        listed.extend(files_from.read_text().splitlines())
        return fake(cmd, *args, **kwargs)

    written = prefetch_missing_objects(
        [first, second],
        source=str(remote_assets),
        cache_root=cache_root,
        run=wrapping_run,
    )

    assert sorted(written) == sorted([first, second])
    assert len(recorded) == 1
    assert listed == [
        f"objects/sha256/{first}",
        f"objects/sha256/{second}",
    ]


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not installed")
def test_prefetch_with_real_rsync_copies_file_and_folder(cache_root, remote_assets):
    file_digest = _write_object(remote_assets, b"real-rsync-file")
    folder_digest = _write_folder_object(remote_assets, {"n.txt": b"nested"})

    written = prefetch_missing_objects(
        [file_digest, folder_digest],
        source=str(remote_assets),
        cache_root=cache_root,
    )

    assert sorted(written) == sorted([file_digest, folder_digest])
    file_path = cache_root / "objects" / "sha256" / file_digest
    folder_path = cache_root / "objects" / "sha256" / folder_digest
    assert file_path.read_bytes() == b"real-rsync-file"
    assert (folder_path / "n.txt").read_bytes() == b"nested"


def test_prefetch_ssh_local_objects_rsyncs_only_localstorage(monkeypatch):
    from types import SimpleNamespace

    from psynet.asset import LocalStorage
    from psynet.data import _prefetch_ssh_local_objects

    local = LocalStorage()
    local_digest = "a" * 64
    skipped_digest = "b" * 64
    captured = {}

    local_asset = SimpleNamespace(sha256_contents=local_digest, storage=local)
    s3_asset = SimpleNamespace(sha256_contents=skipped_digest, storage=object())

    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    monkeypatch.setattr(
        docker_ssh,
        "CONFIGURED_HOSTS",
        {"demo": {"host": "example.com", "user": "alice"}},
    )

    class FakeExecutor:
        def __init__(self, host, user=None):
            self.host = host
            self.user = user

        def run(self, command, raise_=True):
            if command == "command -v rsync":
                return "/usr/bin/rsync\n"
            if command == "echo $HOME":
                return "/home/alice\n"
            raise AssertionError(command)

    monkeypatch.setattr(docker_ssh, "Executor", FakeExecutor)
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.local_rsync_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "dallinger.command_line.utils.get_server_pem_path",
        lambda: "/tmp/key.pem",
    )
    monkeypatch.setattr(
        "psynet.experiment.import_local_experiment",
        lambda: {"class": SimpleNamespace(asset_storage=local)},
    )

    def fake_prefetch(digests, **kwargs):
        captured["digests"] = list(digests)
        captured["source"] = kwargs["source"]
        captured["ssh_command"] = kwargs["ssh_command"]
        return list(digests)

    monkeypatch.setattr(
        "psynet.export.ssh_rsync.prefetch_missing_objects",
        fake_prefetch,
    )
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.missing_object_digests",
        _missing_once_then_empty(),
    )

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    _prefetch_ssh_local_objects(
        [local_asset, s3_asset],
        "demo",
        Logger(),
    )

    assert captured["digests"] == [local_digest]
    assert captured["source"] == "alice@example.com:/home/alice/psynet-data/assets/"
    assert "-i" in captured["ssh_command"]
    assert "/tmp/key.pem" in captured["ssh_command"]


def test_rsync_missing_warning_text_tells_user_how_to_install():
    local = rsync_missing_warning_text(location="local")
    assert local.startswith("WARNING:")
    assert "this computer" in local
    assert "sudo apt install rsync" in local
    assert "brew install rsync" in local
    assert "cannot copy" in local
    assert "SFTP" not in local

    remote = rsync_missing_warning_text(location="remote", host="example.com")
    assert remote.startswith("WARNING:")
    assert "example.com" in remote
    assert "sudo apt install rsync" in remote
    assert "On the server" in remote


def test_emit_rsync_missing_warning_prints_to_stderr(capsys):
    emit_rsync_missing_warning(location="remote", host="example.com")
    captured = capsys.readouterr()
    assert "WARNING:" in captured.err
    assert "example.com" in captured.err
    assert "sudo apt install rsync" in captured.err
    assert captured.out == ""


def _prefetch_test_assets():
    from types import SimpleNamespace

    from psynet.asset import LocalStorage

    local = LocalStorage()
    asset = SimpleNamespace(sha256_contents="a" * 64, storage=local)
    return local, asset


def _patch_prefetch_ssh_host(monkeypatch, executor_cls):
    import importlib
    from types import SimpleNamespace

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    monkeypatch.setattr(
        docker_ssh,
        "CONFIGURED_HOSTS",
        {"demo": {"host": "example.com", "user": "alice"}},
    )
    monkeypatch.setattr(docker_ssh, "Executor", executor_cls)
    monkeypatch.setattr(
        "dallinger.command_line.utils.get_server_pem_path",
        lambda: "/tmp/key.pem",
    )
    local, asset = _prefetch_test_assets()
    monkeypatch.setattr(
        "psynet.experiment.import_local_experiment",
        lambda: {"class": SimpleNamespace(asset_storage=local)},
    )
    return asset


def _missing_once_then_empty():
    """Pretend objects are missing before rsync and cached after it."""
    calls = {"n": 0}

    def fake(digests, cache_root=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return list(digests)
        return []

    return fake


def test_prefetch_warns_when_local_rsync_missing(monkeypatch):
    from psynet.data import _prefetch_ssh_local_objects

    warnings = []
    monkeypatch.setattr("psynet.export.ssh_rsync.local_rsync_available", lambda: False)
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.emit_rsync_missing_warning",
        lambda **kwargs: warnings.append(kwargs) or "warned",
    )
    called = {"executor": 0, "prefetch": 0}

    class BoomExecutor:
        def __init__(self, *args, **kwargs):
            called["executor"] += 1

    asset = _patch_prefetch_ssh_host(monkeypatch, BoomExecutor)
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.prefetch_missing_objects",
        lambda *a, **k: called.__setitem__("prefetch", called["prefetch"] + 1),
    )
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.missing_object_digests",
        lambda digests, cache_root=None: list(digests),
    )

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    with pytest.raises(RsyncRequiredError):
        _prefetch_ssh_local_objects([asset], "demo", Logger())
    assert warnings == [{"location": "local"}]
    assert called["executor"] == 0
    assert called["prefetch"] == 0


def test_prefetch_warns_when_remote_rsync_missing(monkeypatch):
    from psynet.data import _prefetch_ssh_local_objects

    warnings = []
    monkeypatch.setattr("psynet.export.ssh_rsync.local_rsync_available", lambda: True)
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.emit_rsync_missing_warning",
        lambda **kwargs: warnings.append(kwargs) or "warned",
    )
    called = {"prefetch": 0}

    class RemoteMissingExecutor:
        def __init__(self, host, user=None):
            self.host = host

        def run(self, command, raise_=True):
            if command == "command -v rsync":
                return ""
            raise AssertionError(command)

    asset = _patch_prefetch_ssh_host(monkeypatch, RemoteMissingExecutor)
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.prefetch_missing_objects",
        lambda *a, **k: called.__setitem__("prefetch", called["prefetch"] + 1),
    )
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.missing_object_digests",
        lambda digests, cache_root=None: list(digests),
    )

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    with pytest.raises(RsyncRequiredError):
        _prefetch_ssh_local_objects([asset], "demo", Logger())
    assert warnings == [{"location": "remote", "host": "example.com"}]
    assert called["prefetch"] == 0


def test_prefetch_raises_when_rsync_leaves_objects_uncached(monkeypatch):
    from psynet.data import _prefetch_ssh_local_objects

    class FakeExecutor:
        def __init__(self, host, user=None):
            self.host = host
            self.user = user

        def run(self, command, raise_=True):
            if command == "command -v rsync":
                return "/usr/bin/rsync\n"
            if command == "echo $HOME":
                return "/home/alice\n"
            raise AssertionError(command)

    asset = _patch_prefetch_ssh_host(monkeypatch, FakeExecutor)
    monkeypatch.setattr("psynet.export.ssh_rsync.local_rsync_available", lambda: True)
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.prefetch_missing_objects",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "psynet.export.ssh_rsync.missing_object_digests",
        lambda digests, cache_root=None: list(digests),
    )

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    with pytest.raises(RsyncRequiredError, match="still missing"):
        _prefetch_ssh_local_objects([asset], "demo", Logger())


def test_ssh_asset_export_does_not_use_sftp(tmp_path):
    from psynet.asset import LocalStorage

    storage = LocalStorage()
    asset = type("Asset", (), {"var": type("V", (), {"file_system_path": "/nope"})()})()
    with pytest.raises(RsyncRequiredError, match="rsync"):
        storage._export_via_ssh(asset, str(tmp_path / "out"), "host", "user")
