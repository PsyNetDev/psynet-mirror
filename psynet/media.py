import json
import os
import shutil
import struct
import tempfile
import wave
from functools import cache

import boto3
from dallinger.config import get_config

from .utils import get_logger

logger = get_logger()


def make_batch_file(in_files, output_path):
    with open(output_path, "wb") as output:
        for in_file in in_files:
            b = os.path.getsize(in_file)
            output.write(struct.pack("I", b))
            with open(in_file, "rb") as i:
                output.write(i.read())


def _sep_batch_file(input_path: str):
    with open(input_path, "rb") as f:
        bb = f.read()

    separated_batch = []
    offset = 0
    while offset < len(bb):
        size = struct.unpack("I", bb[offset : offset + 4])[0]
        offset += 4
        offset += size
        separated_batch.append(bb[offset - size : offset])
    return separated_batch


def unpack_batch_file(input_path: str, output_paths: list[str]):
    """
    Converts a batch file into a list of files. It's the inverse of make_batch_file.
    Parameters
    ----------
    input_path: str, path to the batch file
    output_paths: list of str, paths to the output files

    Returns output_paths
    -------

    """
    separated_batch = _sep_batch_file(input_path)

    assert len(output_paths) == len(separated_batch)

    for idx, output_bytes in enumerate(separated_batch):
        output_path = output_paths[idx]
        with open(output_path, "wb") as f:
            f.write(output_bytes)
    return output_paths


@cache
def get_aws_credentials(capitalize=False):
    config = get_config()
    if not config.ready:
        config.load()
    cred = {
        "aws_access_key_id": config.get("aws_access_key_id"),
        "aws_secret_access_key": config.get("aws_secret_access_key"),
        "region_name": config.get("aws_region"),
    }
    cred = {key: value for key, value in cred.items() if value}
    if capitalize:
        cred = {key.upper(): value for key, value in cred.items()}
    return cred


def get_s3_client():
    from psynet.test_helpers.mock_s3 import get_configured_mock_s3_client

    mock_client = get_configured_mock_s3_client()
    if mock_client is not None:
        return mock_client

    return boto3.client("s3", **get_aws_credentials())


def get_s3_resource():
    from psynet.test_helpers.mock_s3 import get_configured_mock_s3_resource

    mock_resource = get_configured_mock_s3_resource()
    if mock_resource is not None:
        return mock_resource

    return boto3.resource("s3", **get_aws_credentials())


def get_s3_bucket(bucket_name: str):
    # pylint: disable=no-member
    resource = get_s3_resource()
    return resource.Bucket(bucket_name)


def setup_bucket_for_presigned_urls(bucket_name, public_read=False):
    logger.info("Setting bucket CORSRules and policies...")

    s3_resource = get_s3_resource()
    bucket = s3_resource.Bucket(bucket_name)

    cors = bucket.Cors()

    config = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "PUT"],
                "AllowedOrigins": ["*"],
            }
        ]
    }

    cors.delete()
    cors.put(CORSConfiguration=config)

    if public_read:
        bucket_policy = s3_resource.BucketPolicy(bucket_name)

        new_policy = json.dumps(
            {
                "Version": "2008-10-17",
                "Statement": [
                    {
                        "Sid": "AllowPublicRead",
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket_name}/*",
                    }
                ],
            }
        )
        bucket_policy.put(Policy=new_policy)


def make_bucket_public(bucket_name):
    logger.info(
        "Verifying that the S3 bucket '%s' is correctly configured for public access...",
        bucket_name,
    )

    s3_resource = get_s3_resource()
    bucket = s3_resource.Bucket(bucket_name)
    bucket.Acl().put(ACL="public-read")

    cors = bucket.Cors()

    config = {"CORSRules": [{"AllowedMethods": ["GET"], "AllowedOrigins": ["*"]}]}

    cors.delete()
    cors.put(CORSConfiguration=config)

    bucket_policy = s3_resource.BucketPolicy(bucket_name)
    new_policy = json.dumps(
        {
            "Version": "2008-10-17",
            "Statement": [
                {
                    "Sid": "AllowPublicRead",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket_name}/*",
                }
            ],
        }
    )
    bucket_policy.put(Policy=new_policy)


def recode_wav(file_path):
    with tempfile.NamedTemporaryFile() as temp_file:
        shutil.copyfile(file_path, temp_file.name)

        with wave.open(temp_file.name, "rb") as in_wave:
            params = in_wave.getparams()

            with wave.open(file_path, "wb") as out_wave:
                out_wave.setparams(params)

                chunk_size = 1024
                data = in_wave.readframes(chunk_size)
                while data:
                    out_wave.writeframes(data)
                    data = in_wave.readframes(chunk_size)
