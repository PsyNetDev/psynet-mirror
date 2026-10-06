import os
import shutil
import tempfile
from glob import glob
from os import makedirs
from os.path import basename, join
from uuid import uuid4

import pytest

from psynet.asset import S3Storage
from psynet.cache import IMMUTABLE_CACHE_CONTROL
from psynet.media import get_s3_client


def get_s3_storage(transfer_backend):
    return S3Storage("psynet-tests", "s3-tests", transfer_backend)


@pytest.fixture(params=["mock", "real"])
def s3_target(request):
    """Run against the filesystem mock, and against real S3 when ``PSYNET_TEST_REAL_S3=1``."""
    if request.param == "mock":
        request.getfixturevalue("mock_s3_root")
    elif os.environ.get("PSYNET_TEST_REAL_S3") != "1":
        pytest.skip(
            "Set PSYNET_TEST_REAL_S3=1 to test against the psynet-tests bucket."
        )
    return request.param


def create_test_file(test_folder, test_file_path):
    makedirs(test_folder, exist_ok=True)
    with open(test_file_path, "w") as file:
        file.write("Test")


def file_exists_on_s3(storage, s3_key):
    return storage.check_cache_for_file(s3_key, False)


def folder_exists_on_s3(storage, s3_key):
    return storage.check_cache_for_folder(s3_key, False)


def remove_test_folder(test_folder):
    shutil.rmtree(test_folder)


def get_test_files(test_folder):
    return sorted(glob(test_folder + "/*"))


def run_test(storage, remote_prefix=""):
    with tempfile.TemporaryDirectory() as tempdir:
        test_folder = join(tempdir, "test_folder")
        test_file_name = "test_file"
        test_file_path = join(test_folder, test_file_name)
        test_file_path_downloaded = test_file_path + "_downloaded"
        remote_prefix = remote_prefix.strip("/")
        remote_test_file_name = join(remote_prefix, test_file_name + "_remote")
        remote_test_folder = join(remote_prefix, "test_folder_remote")

        create_test_file(test_folder, test_file_path)

        # File test
        storage.upload_file(test_file_path, remote_test_file_name)
        assert file_exists_on_s3(storage, remote_test_file_name), (
            "File was not uploaded to S3"
        )
        storage.download_file(remote_test_file_name, test_file_path_downloaded)
        listed_files = get_test_files(test_folder)
        assert len(listed_files) == 2
        storage.delete_file(remote_test_file_name)
        assert not file_exists_on_s3(storage, remote_test_file_name), (
            "File was not removed on S3"
        )

        # Folder test
        storage.upload_folder(test_folder, remote_test_folder)
        assert folder_exists_on_s3(storage, remote_test_folder)
        for file_path in listed_files:
            remote_file_path = join(remote_test_folder, basename(file_path))
            assert file_exists_on_s3(storage, remote_file_path)
        remove_test_folder(test_folder)
        storage.download_folder(remote_test_folder, test_folder)
        assert listed_files == get_test_files(test_folder)
        storage.delete_folder(remote_test_folder)
        assert not folder_exists_on_s3(storage, remote_test_folder)
        remove_test_folder(test_folder)


def test_s3_storage_awscli():
    # Only run the test if AWS CLI is installed
    from shutil import which

    if which("aws") is not None:
        storage = get_s3_storage("awscli")
        remote_prefix = f"s3-tests/{uuid4().hex}"
        try:
            run_test(storage, remote_prefix)
        finally:
            storage.delete_folder(remote_prefix)


def test_s3_storage_boto3(s3_target):
    storage = get_s3_storage("boto3")
    remote_prefix = f"s3-tests/{uuid4().hex}"
    try:
        run_test(storage, remote_prefix)
    finally:
        storage.delete_folder(remote_prefix)


def test_list_files_in_missing_bucket_returns_empty_list(s3_target):
    storage = S3Storage(f"psynet-missing-{uuid4().hex}", "s3-tests")
    assert storage.list_files_with_prefix("", use_cache=False) == []


def test_s3_deposit_sets_immutable_cache_control_for_files_and_folders(
    s3_target, tmp_path
):
    storage = get_s3_storage("boto3")
    if s3_target == "mock":
        storage.create_bucket(storage.s3_bucket)
    prefix = uuid4().hex
    source = tmp_path / "cached.txt"
    source.write_text("cached", encoding="utf-8")

    file_asset = type("Asset", (), {"is_folder": False, "input_path": str(source)})()
    folder = tmp_path / "cached"
    folder.mkdir()
    nested = folder / "nested.txt"
    nested.write_text("nested", encoding="utf-8")
    folder_asset = type("Asset", (), {"is_folder": True, "input_path": str(folder)})()

    try:
        storage._receive_deposit(file_asset, f"{prefix}/cached.txt")
        storage._receive_deposit(folder_asset, f"{prefix}/cached-folder")

        for key in ("cached.txt", "cached-folder/nested.txt"):
            metadata = get_s3_client().head_object(
                Bucket=storage.s3_bucket,
                Key=f"s3-tests/{prefix}/{key}",
            )
            assert metadata["CacheControl"] == IMMUTABLE_CACHE_CONTROL
    finally:
        storage.delete_folder(f"s3-tests/{prefix}")
