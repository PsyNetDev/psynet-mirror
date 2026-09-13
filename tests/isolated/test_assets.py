import os
import tempfile
from urllib import request

import pytest
from dallinger import db

import psynet.experiment  # noqa -- Need to import this for SQLAlchemy registrations to work properly
from psynet.asset import (
    CachedAsset,
    CachedFunctionAsset,
    ExperimentAsset,
    ExternalAsset,
    LocalStorage,
    OnDemandAsset,
    asset,
)
from psynet.pytest_psynet import path_to_test_experiment
from psynet.redis import redis_vars
from psynet.trial.chain import ChainNode
from psynet.trial.static import StaticTrial


def placeholder_function(path, param):
    with open(path, "w") as f:
        f.write(f"Generated content: {param}")


class FinalizeDefinitionTrial(StaticTrial):
    time_estimate = 1

    def make_definition(self, experiment, participant):
        return {"param": "initial"}

    def finalize_definition(self, definition, experiment, participant):
        self.add_assets(
            {
                "generated": OnDemandAsset(
                    function=placeholder_function,
                    arguments={},
                )
            }
        )
        return definition

    def show_trial(self, experiment, participant):
        raise NotImplementedError


class MultiplyAsset(ExperimentAsset):
    def after_deposit(self):
        with open(self.input_path, "r") as f:
            self.var.x = int(f.read())
            self.var.y = self.var.x * 3


@pytest.fixture
def debug_storage(in_experiment_directory):
    with tempfile.TemporaryDirectory() as tempdir:
        yield LocalStorage(tempdir)


@pytest.fixture
def folder_asset(debug_storage):
    with tempfile.TemporaryDirectory() as tempdir:
        path_1 = os.path.join(tempdir, "file_1.txt")
        path_2 = os.path.join(tempdir, "file_2.txt")

        subdir = os.path.join(tempdir, "subdir")
        path_3 = os.path.join(subdir, "file_3.txt")

        with open(path_1, "w") as f:
            f.write("File 1")

        with open(path_2, "w") as f:
            f.write("File 2")

        os.mkdir(subdir)

        with open(path_3, "w") as f:
            f.write("File 3")

        asset = ExperimentAsset(
            "test_folder_asset",
            tempdir,
            is_folder=True,
        )
        asset.deposit(debug_storage)

        yield asset


@pytest.fixture
def folder_asset_clone(debug_storage):
    with tempfile.TemporaryDirectory() as tempdir:
        path_1 = os.path.join(tempdir, "file_1.txt")
        path_2 = os.path.join(tempdir, "file_2.txt")

        subdir = os.path.join(tempdir, "subdir")
        path_3 = os.path.join(subdir, "file_3.txt")

        with open(path_1, "w") as f:
            f.write("File 1")

        with open(path_2, "w") as f:
            f.write("File 2")

        os.mkdir(subdir)

        with open(path_3, "w") as f:
            f.write("File 3")

        asset = ExperimentAsset(
            "test_folder_asset_2",
            tempdir,
            is_folder=True,
        )
        asset.deposit(debug_storage)

        yield asset


@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
class AssetTests:
    def test_lambda_function(self):
        with pytest.raises(ValueError) as e:
            CachedFunctionAsset(function=lambda path, x: x + 1)
        assert (
            str(e.value)
            == "'function' cannot be a lambda function, please provide a named function instead"
        )

    def test_key(self):
        def f(path):
            pass

        asset_1 = CachedFunctionAsset(function=f)
        asset_2 = CachedFunctionAsset(function=f, key="asset_2")

        assert not asset_1.has_key
        assert asset_2.has_key

    def test_md5_folder(self, folder_asset, folder_asset_clone):
        assert folder_asset.is_folder
        assert folder_asset.get_md5_contents() == folder_asset_clone.get_md5_contents()

    def test_infer_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            file_path = tempdir + "/file.txt"
            with open(file_path, "w") as file:
                file.write("Hello!")

                asset = ExperimentAsset(
                    local_key="test",
                    input_path=file_path,
                )
                assert isinstance(asset.is_folder, bool) and not asset.is_folder

                asset_2 = ExperimentAsset(
                    local_key="test_2",
                    input_path=tempdir,
                )
                assert isinstance(asset_2.is_folder, bool) and asset_2.is_folder

    def test_export_subfile(
        self, folder_asset, debug_storage, deployment_info, db_session
    ):
        folder_asset.deposit(storage=debug_storage)

        # Exporting the whole folder at once
        with tempfile.TemporaryDirectory() as tempdir:
            folder_asset.export(tempdir)

            with open(tempdir + "/file_1.txt", "r") as file:
                assert file.read() == "File 1"

            with open(tempdir + "/file_2.txt", "r") as file:
                assert file.read() == "File 2"

        # Exporting single files
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = tempdir + "/file_2.txt"
            folder_asset.export_subfile("file_2.txt", temp_path)

            assert not os.path.exists(tempdir + "/file_1.txt")
            assert os.path.exists(tempdir + "/file_2.txt")

            with open(temp_path, "r") as file:
                assert file.read() == "File 2"

        # Export subdirectory
        with tempfile.TemporaryDirectory() as tempdir:
            folder_asset.export_subfolder("subdir", tempdir)

            with open(os.path.join(tempdir, "file_3.txt"), "r") as file:
                assert file.read() == "File 3"

    @pytest.mark.parametrize("async_", [True, False])
    def test_after_deposit(async_, db_session, debug_storage, deployment_info):
        from dallinger import db

        from psynet.utils import wait_until

        try:
            file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt")
            file.write("42")
            file.flush()

            asset = MultiplyAsset(
                "test",
                file.name,
            )

            asset.deposit(debug_storage, async_=async_)

            def deposit_complete():
                db.session.refresh(asset)
                return asset.deposited

            wait_until(deposit_complete, max_wait=5, poll_interval=0.2)

            assert asset.var.x == 42
            assert asset.var.y == 126

        finally:
            os.remove(file.name)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_access_assets(
    node,
    trial_class,
    debug_storage,
    experiment_object,
    participant,
    launched_experiment,
):
    trials = [
        trial_class(
            experiment=experiment_object,
            node=node,
            participant=participant,
            propagate_failure=False,
            is_repeat_trial=False,
        )
        for _ in range(2)
    ]
    for t in trials:
        db.session.add(t)
    db.session.commit()

    with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
        f.write("Hello!")
        f.flush()

        node_asset = ExperimentAsset(
            local_key="node_asset",
            input_path=f.name,
            parent=node,
        )
        node_asset.deposit(debug_storage)

        for t in trials:
            trial_asset = ExperimentAsset(
                local_key="trial_asset",
                input_path=f.name,
                parent=t,
            )
            trial_asset.deposit(debug_storage)

    db.session.commit()

    assert len(node.assets) == 1
    assert isinstance(node.assets["node_asset"], ExperimentAsset)
    assert node.assets["node_asset"].export_path.endswith(".txt")
    assert not node.assets["node_asset"].key_within_experiment.endswith(".txt")

    for t in trials:
        assert len(t.assets) == 1
        assert isinstance(t.assets["trial_asset"], ExperimentAsset)
        assert t.assets["trial_asset"].export_path.endswith(".txt")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_add_asset_does_not_reobfuscate_deposited_asset(trial, launched_experiment):
    with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
        f.write("Hello!")
        f.flush()

        cached_asset = CachedAsset(
            local_key="cached_asset",
            input_path=f.name,
        )
        cached_asset.deposit(launched_experiment.asset_storage)

        original_host_path = cached_asset.host_path
        original_url = cached_asset.url
        original_local_key = cached_asset.local_key
        original_access_token = cached_asset.access_token
        original_object_path = cached_asset.object_path
        cached_asset.node_definition = {"marker": "original"}

        assert original_host_path.startswith("objects/sha256/")
        assert original_object_path == original_host_path
        assert original_url == f"/asset/{original_access_token}"

        trial.add_asset("image_left", cached_asset)

        assert cached_asset.host_path == original_host_path
        assert cached_asset.object_path == original_object_path
        assert cached_asset.url == original_url
        assert cached_asset.access_token == original_access_token
        assert cached_asset.local_key == original_local_key
        assert cached_asset.node_definition == {"marker": "original"}

        db.session.commit()

        base_url = redis_vars.get("base_url")
        assert base_url
        url = f"{base_url}{cached_asset.url}"
        with request.urlopen(url) as response:
            assert response.status == 200
            assert response.read() == b"Hello!"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_add_asset_relink_deposited_asset_across_trials(
    trial_class,
    experiment_object,
    participant,
    node,
    launched_experiment,
):
    trials = [
        trial_class(
            experiment=experiment_object,
            node=node,
            participant=participant,
            propagate_failure=False,
            is_repeat_trial=False,
        )
        for _ in range(2)
    ]
    for t in trials:
        db.session.add(t)
    db.session.commit()

    with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
        f.write("Hello!")
        f.flush()

        cached_asset = CachedAsset(
            local_key="cached_asset",
            input_path=f.name,
        )
        cached_asset.deposit(launched_experiment.asset_storage)

        original_host_path = cached_asset.host_path
        original_url = cached_asset.url
        original_local_key = cached_asset.local_key

        trials[0].add_asset("link_a", cached_asset)
        trials[1].add_asset("link_b", cached_asset)

        assert cached_asset.host_path == original_host_path
        assert cached_asset.url == original_url
        assert cached_asset.local_key == original_local_key
        assert trials[0].assets["link_a"] is cached_asset
        assert trials[1].assets["link_b"] is cached_asset


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_add_asset_sets_definition_for_on_demand_asset(trial):
    on_demand_asset = OnDemandAsset(
        function=placeholder_function,
        arguments={},
    )
    trial.definition["param"] = "from_definition"

    trial.add_asset("generated", on_demand_asset)

    assert on_demand_asset.arguments["param"] == "from_definition"
    assert on_demand_asset.node_definition == trial.definition


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_add_asset_does_not_override_definition_for_deposited_on_demand_asset(
    trial, launched_experiment
):
    on_demand_asset = OnDemandAsset(
        function=placeholder_function,
        arguments={"param": "original"},
    )
    on_demand_asset.deposit(launched_experiment.asset_storage)
    on_demand_asset.node_definition = {"marker": "original"}
    trial.definition["param"] = "new"

    trial.add_asset("generated", on_demand_asset)

    assert on_demand_asset.arguments["param"] == "original"
    assert on_demand_asset.node_definition == {"marker": "original"}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_add_asset_external_asset_does_not_mutate_url(trial):
    external_asset = ExternalAsset(
        "http://example.com/example.mp3",
        local_key="external_asset",
    )
    original_url = external_asset.url
    original_host_path = external_asset.host_path

    trial.add_asset("external", external_asset)

    assert external_asset.url == original_url
    assert external_asset.host_path == original_host_path
    assert trial.assets["external"] is external_asset


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_add_asset_external_asset_sets_missing_metadata(trial):
    external_asset = ExternalAsset("http://example.com/example.mp3")

    assert external_asset.local_key is None

    trial.add_asset("external", external_asset)

    assert external_asset.parent is trial
    assert external_asset.local_key == "external"
    assert external_asset.key_within_module
    assert "external" in external_asset.key_within_module
    assert external_asset.export_path
    assert external_asset.export_path != "common/.mp3"
    assert trial.assets["external"] is external_asset


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_chain_node_stage_assets_overwrites_undeposited_metadata(
    launched_experiment, participant
):
    with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
        f.write("Hello!")
        f.flush()

        staged_asset = ExperimentAsset(
            input_path=f.name,
            local_key="original_key",
            parent=participant,
        )
        node = ChainNode(
            definition={"seed": "x"},
            assets={"stimulus": staged_asset},
            module_id="chain_module",
        )

        node.stage_assets(launched_experiment)

        assert staged_asset.parent is node
        assert staged_asset.local_key == "stimulus"
        assert staged_asset.module_id == "chain_module"
        assert staged_asset.node_definition == node.definition
        assert node.assets["stimulus"] is staged_asset


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_update_metadata_clears_module_id_when_parent_missing(launched_experiment):
    with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
        f.write("Hello!")
        f.flush()

        staged_asset = ExperimentAsset(
            input_path=f.name,
            local_key="original_key",
            module_id="stale_module",
        )
        node = ChainNode(
            definition={"seed": "x"},
            assets={"stimulus": staged_asset},
            module_id=None,
        )

        node.stage_assets(launched_experiment)

        assert staged_asset.module_id is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_add_asset_sets_missing_metadata_for_new_assets(trial, participant):
    with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
        f.write("Hello!")
        f.flush()

        new_asset = ExperimentAsset(
            input_path=f.name,
            local_key="original_key",
            parent=participant,
        )

        assert new_asset.local_key == "original_key"
        assert getattr(new_asset, "node_definition", None) is None

        trial.add_asset("image_right", new_asset)

        assert new_asset.local_key == "image_right"
        assert new_asset.parent is trial
        assert new_asset.node_definition == trial.definition


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_finalize_assets_does_not_override_deposited_on_demand_asset(
    trial, launched_experiment
):
    on_demand_asset = OnDemandAsset(
        function=placeholder_function,
        arguments={"param": "original"},
    )
    on_demand_asset.deposit(launched_experiment.asset_storage)
    on_demand_asset.node_definition = {"marker": "original"}

    trial.add_asset("generated", on_demand_asset)
    trial.finalize_assets()

    assert on_demand_asset.arguments["param"] == "original"
    assert on_demand_asset.node_definition == {"marker": "original"}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_finalize_assets_keeps_deposited_on_demand_asset_definition(
    experiment_object,
    node,
    participant,
):
    trial = FinalizeDefinitionTrial(
        experiment=experiment_object,
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    asset = trial.assets["generated"]
    assert asset.arguments["param"] == "initial"

    trial.definition["param"] = "changed"
    trial.finalize_assets()

    assert asset.arguments["param"] == "initial"


def test_asset_constructor():
    """Test the asset constructor function with different input types and parameters."""
    import tempfile
    from pathlib import Path

    # Test external URL asset
    url_asset = asset(
        "http://example.com/file.mp3", description="An external audio file"
    )
    assert isinstance(url_asset, ExternalAsset)
    assert url_asset.url == "http://example.com/file.mp3"
    assert url_asset.description == "An external audio file"

    # Test local file asset
    with tempfile.NamedTemporaryFile(suffix=".txt") as f:
        f.write(b"test content")
        f.flush()
        file_asset = asset(f.name, description="A local file")
        assert isinstance(file_asset, ExperimentAsset)
        assert file_asset.input_path == f.name
        assert file_asset.description == "A local file"

        # Test Path object input
        path_asset = asset(Path(f.name), description="A path object file")
        assert isinstance(path_asset, ExperimentAsset)
        assert str(path_asset.input_path) == f.name

        # Test cached file asset
        cached_asset = asset(f.name, cache=True, description="A cached file asset")
        assert isinstance(cached_asset, CachedAsset)
        assert cached_asset.input_path == f.name
        assert cached_asset.description == "A cached file asset"

    # Test cached function asset
    cached_asset = asset(
        placeholder_function, cache=True, description="A cached function asset"
    )
    assert isinstance(cached_asset, CachedFunctionAsset)
    assert cached_asset.function == placeholder_function
    assert cached_asset.description == "A cached function asset"

    # Test function asset - on demand
    on_demand_asset = asset(
        placeholder_function, on_demand=True, description="An on-demand function asset"
    )
    assert isinstance(on_demand_asset, OnDemandAsset)
    assert on_demand_asset.function == placeholder_function
    assert on_demand_asset.description == "An on-demand function asset"

    # Test function asset with arguments
    args_asset = asset(
        placeholder_function,
        on_demand=True,
        arguments={"param": "value"},
        description="Function with args",
    )
    assert isinstance(args_asset, OnDemandAsset)
    assert args_asset.arguments == {"param": "value"}

    # Test invalid combinations
    with pytest.raises(
        ValueError,
        match="Sorry, currently function assets can't be both cached and on-demand.",
    ):
        asset(placeholder_function, cache=True, on_demand=True)

    with pytest.raises(
        ValueError,
        match=(
            "Sorry, currently function assets must be marked as either cached or on-demand. "
            "Select the former if you want to pre-generate your assets, or the latter otherwise."
        ),
    ):
        asset(placeholder_function)
