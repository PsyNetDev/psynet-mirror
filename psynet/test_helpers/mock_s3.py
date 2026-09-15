"""
Minimal S3 client/resource mock for PsyNet's S3 tests.

This helper intentionally implements only the boto surface exercised by the
lightweight S3 tests: bucket creation, file upload/download/copy/delete, object
metadata lookups, bucket object listings, and paginator-based object listings.

Use the ``mock_s3_root`` pytest fixture to route both current-process and
subprocess S3 calls to this filesystem-backed mock. The fixture sets
``PSYNET_MOCK_S3_ROOT``, which is read by the helpers in this module. The mock
does not provide a public HTTP endpoint, so it verifies storage operations and
exports, not browser reachability of generated ``https://s3.amazonaws.com``
URLs.
"""

import os
import shutil
from datetime import datetime, timezone
from functools import cache
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import botocore.exceptions


def _client_error(code: str, operation_name: str):
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": code}},
        operation_name,
    )


class MockS3Client:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.object_metadata = {}

    def _bucket_path(self, bucket_name: str) -> Path:
        return self.root / bucket_name

    def _object_path(self, bucket_name: str, key: str) -> Path:
        return self._bucket_path(bucket_name).joinpath(*PurePosixPath(key).parts)

    def create_bucket(self, Bucket: str):
        self._bucket_path(Bucket).mkdir(parents=True, exist_ok=True)

    def _has_bucket(self, bucket_name: str) -> bool:
        return self._bucket_path(bucket_name).is_dir()

    def _list_objects(
        self, bucket_name: str, prefix: str = "", delimiter: str | None = None
    ):
        if not self._has_bucket(bucket_name):
            return []

        contents = []
        for path in self._bucket_path(bucket_name).rglob("*"):
            if not path.is_file():
                continue

            key = path.relative_to(self._bucket_path(bucket_name)).as_posix()
            if not key.startswith(prefix):
                continue

            if delimiter == "/":
                suffix = key[len(prefix) :].lstrip("/")
                if "/" in suffix:
                    continue

            contents.append(
                {
                    "Key": key,
                    "LastModified": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ),
                }
            )

        return contents

    def _delete_prefix(self, bucket_name: str, prefix: str):
        for obj in list(self._list_objects(bucket_name=bucket_name, prefix=prefix)):
            self._delete_object(bucket_name, obj["Key"])

    def _upload_file(
        self,
        filename: str,
        bucket_name: str,
        key: str,
        extra_args: dict | None = None,
    ):
        if not self._has_bucket(bucket_name):
            raise _client_error("NoSuchBucket", "PutObject")
        target = self._object_path(bucket_name, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(filename, target)
        self.object_metadata[(bucket_name, key)] = dict(extra_args or {})

    def _download_file(self, bucket_name: str, key: str, filename: str):
        source = self._object_path(bucket_name, key)
        if not source.is_file():
            raise _client_error("NoSuchKey", "GetObject")
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, filename)

    def _copy(self, copy_source: dict, bucket_name: str, key: str):
        source = self._object_path(copy_source["Bucket"], copy_source["Key"])
        if not source.is_file():
            raise _client_error("NoSuchKey", "CopyObject")
        if not self._has_bucket(bucket_name):
            raise _client_error("NoSuchBucket", "CopyObject")
        target = self._object_path(bucket_name, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def _delete_object(self, bucket_name: str, key: str):
        path = self._object_path(bucket_name, key)
        if path.exists():
            path.unlink()
        self.object_metadata.pop((bucket_name, key), None)

    def _head_object(self, bucket_name: str, key: str):
        path = self._object_path(bucket_name, key)
        if not path.is_file():
            raise _client_error("NoSuchKey", "HeadObject")
        return {
            "LastModified": datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ),
            **self.object_metadata.get((bucket_name, key), {}),
        }

    def _put_object(self, bucket_name: str, key: str, body):
        if not self._has_bucket(bucket_name):
            raise _client_error("NoSuchBucket", "PutObject")
        target = self._object_path(bucket_name, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, str):
            body = body.encode("utf-8")
        target.write_bytes(body)

    def _get_object(self, bucket_name: str, key: str):
        source = self._object_path(bucket_name, key)
        if not source.is_file():
            raise _client_error("NoSuchKey", "GetObject")
        return {"Body": BytesIO(source.read_bytes())}

    def upload_file(
        self,
        Filename: str,
        Bucket: str,
        Key: str,
        ExtraArgs: dict | None = None,
    ):
        self._upload_file(Filename, Bucket, Key, ExtraArgs)

    def download_file(self, Bucket: str, Key: str, Filename: str):
        self._download_file(Bucket, Key, Filename)

    def copy(self, CopySource: dict, Bucket: str, Key: str):
        self._copy(CopySource, Bucket, Key)

    def delete_object(self, Bucket: str, Key: str):
        self._delete_object(Bucket, Key)

    def head_object(self, Bucket: str, Key: str):
        return self._head_object(Bucket, Key)

    def head_bucket(self, Bucket: str):
        if not self._has_bucket(Bucket):
            raise _client_error("404", "HeadBucket")
        return {}

    def put_object(self, Bucket: str, Key: str, Body):
        self._put_object(Bucket, Key, Body)

    def get_object(self, Bucket: str, Key: str):
        return self._get_object(Bucket, Key)

    def get_paginator(self, name: str):
        def paginate(
            Bucket: str, Prefix: str = "", Delimiter: str | None = None, **_kwargs
        ):
            yield {
                "Contents": self._list_objects(
                    bucket_name=Bucket,
                    prefix=Prefix,
                    delimiter=Delimiter,
                )
            }

        return SimpleNamespace(paginate=paginate)


class MockS3ObjectSummary:
    def __init__(self, client: MockS3Client, bucket_name: str, key: str):
        self.client = client
        self.bucket_name = bucket_name
        self.key = key

    @property
    def last_modified(self):
        return self.client._head_object(self.bucket_name, self.key)["LastModified"]

    def delete(self):
        self.client._delete_object(self.bucket_name, self.key)


class MockS3ObjectCollection:
    def __init__(
        self,
        client: MockS3Client,
        bucket_name: str,
        prefix: str = "",
    ):
        self.client = client
        self.bucket_name = bucket_name
        self.prefix = prefix

    def __iter__(self):
        for obj in self.client._list_objects(self.bucket_name, self.prefix):
            yield MockS3ObjectSummary(
                self.client,
                self.bucket_name,
                obj["Key"],
            )

    def filter(self, Prefix: str = ""):
        return type(self)(self.client, self.bucket_name, Prefix)

    def delete(self):
        self.client._delete_prefix(self.bucket_name, self.prefix)


class MockS3NoOpConfiguration:
    def delete(self):
        return None

    def put(self, **_kwargs):
        return None


class MockS3Bucket:
    def __init__(self, client: MockS3Client, bucket_name: str):
        self.client = client
        self.bucket_name = bucket_name
        self.objects = MockS3ObjectCollection(client, bucket_name)

    def Object(self, key: str):
        return MockS3ObjectSummary(self.client, self.bucket_name, key)

    def Acl(self):
        return MockS3NoOpConfiguration()

    def Cors(self):
        return MockS3NoOpConfiguration()


class MockS3Resource:
    def __init__(self, client: MockS3Client):
        self.client = client
        self.meta = SimpleNamespace(client=client)

    def Bucket(self, bucket_name: str):
        return MockS3Bucket(self.client, bucket_name)

    def BucketPolicy(self, _bucket_name: str):
        return MockS3NoOpConfiguration()


@cache
def get_mock_s3_client(root: str):
    return MockS3Client(root)


@cache
def get_mock_s3_resource(root: str):
    return MockS3Resource(get_mock_s3_client(root))


def get_mock_s3_root():
    """
    Get the filesystem root for the test S3 mock, if configured.
    """
    return os.environ.get("PSYNET_MOCK_S3_ROOT")


def get_configured_mock_s3_client():
    """
    Return the configured mock S3 client, if the filesystem mock is enabled.
    """
    root = get_mock_s3_root()
    if root:
        return get_mock_s3_client(root)
    return None


def get_configured_mock_s3_resource():
    """
    Return the configured mock S3 resource, if the filesystem mock is enabled.
    """
    root = get_mock_s3_root()
    if root:
        return get_mock_s3_resource(root)
    return None
