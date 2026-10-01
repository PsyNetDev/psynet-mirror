"""Tests for content-addressed managed assets and access tokens."""

import hashlib
from pathlib import Path

import pytest

from psynet.asset import (
    CachedFunctionAsset,
    ExperimentAsset,
    OnDemandAsset,
    _reject_obfuscate_arg,
)
from psynet.pytest_psynet import path_to_test_experiment
from psynet.utils import content_object_path, sha256_file


def _write_generated_asset(path, payload):
    Path(path).write_bytes(payload.encode())


def test_reject_obfuscate_arg_raises():
    with pytest.raises(TypeError, match="obfuscate"):
        _reject_obfuscate_arg(1)


def test_experiment_asset_rejects_obfuscate_kwarg(tmp_path):
    path = tmp_path / "hello.txt"
    path.write_text("hello")
    with pytest.raises(TypeError, match="obfuscate"):
        ExperimentAsset(input_path=str(path), obfuscate=0)


def test_on_demand_asset_rejects_secret_kwarg():
    with pytest.raises(TypeError, match="secret"):
        OnDemandAsset(
            function=lambda path: None,
            extension=".txt",
            secret="nope",
        )


def test_content_object_path_helper():
    assert content_object_path("abc") == "objects/sha256/abc"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_managed_asset_uses_sha256_object_path_and_access_token(
    launched_experiment, tmp_path
):
    path = tmp_path / "payload.txt"
    path.write_text("content-addressed")
    digest = sha256_file(path)

    asset = ExperimentAsset(
        local_key="payload",
        input_path=str(path),
        extension=".txt",
    )
    asset.deposit(launched_experiment.asset_storage)

    assert asset.sha256_contents == digest
    assert asset.object_path == content_object_path(digest)
    assert asset.host_path == asset.object_path
    assert asset.access_token
    assert asset.url == f"/asset/{asset.access_token}"
    assert asset.url != asset.object_path


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_cached_function_assets_hash_the_generated_bytes(launched_experiment):
    assets = [
        CachedFunctionAsset(
            function=_write_generated_asset,
            arguments={"payload": payload},
            local_key=f"generated-{payload}",
            extension=".txt",
        )
        for payload in ("first", "second")
    ]

    for asset in assets:
        asset.deposit(launched_experiment.asset_storage)

    expected = [
        hashlib.sha256(value.encode()).hexdigest() for value in ("first", "second")
    ]
    assert [asset.sha256_contents for asset in assets] == expected
    assert assets[0].object_path != assets[1].object_path
    for asset, payload in zip(assets, ("first", "second")):
        stored = launched_experiment.asset_storage.get_file_system_path(
            asset.object_path
        )
        assert Path(stored).read_text() == payload
