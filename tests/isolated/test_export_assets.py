import os
import shutil
import tempfile

import pytest
from click import Context
from dallinger import db

from psynet.asset import Asset, ExperimentAsset, ExternalAsset, OnDemandAsset
from psynet.bot import BotDriver
from psynet.command_line import export__local
from psynet.pytest_psynet import path_to_test_experiment
from psynet.utils import generate_text_file

app = "demo-app"


@pytest.fixture(scope="class")
def data_root_dir():
    path = os.path.join("data", f"data-{app}")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def coin_class(experiment_module):
    return experiment_module.Coin


def test_export_path__external_asset():
    asset = ExternalAsset(
        key_within_experiment="test_external_asset",
        url="https://s3.amazonaws.com/headphone-check/antiphase_HC_ISO.wav",
    )
    assert asset.generate_export_path() == "test_external_asset.wav"


def test_export_path__on_demand_asset():
    asset = OnDemandAsset(
        function=generate_text_file,
        key_within_experiment="test_on_demand_asset",
        extension=".txt",
    )
    assert asset.generate_export_path() == "test_on_demand_asset.txt"


@pytest.fixture(scope="class")
def ctx():
    return Context(export__local)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("gibbs")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestAssetExport:
    def test_exp(
        self,
        data_root_dir,
        ctx,
    ):
        # Creating experiment assets with different keys
        with tempfile.NamedTemporaryFile("w") as file:
            file.write("Test asset")
            asset = ExperimentAsset(local_key="test_marked_asset", input_path=file.name)
            asset.deposit()

            asset_2 = ExperimentAsset(
                local_key="test_public_asset",
                input_path=file.name,
            )
            asset_2.deposit()

            asset_3 = ExternalAsset(
                local_key="test_external_asset",
                url="https://s3.amazonaws.com/headphone-check/antiphase_HC_ISO.wav",
            )
            asset_3.deposit()

            asset_4 = OnDemandAsset(
                function=generate_text_file,
                local_key="test_on_demand_asset",
            )
            asset_4.deposit()

            with pytest.raises(TypeError, match="personal"):
                ExperimentAsset(
                    local_key="should_fail", input_path=file.name, personal=True
                )

        db.session.commit()

        assert Asset.query.count() == 4

        self._test_asset_export_modes(ctx)

        bot_driver = BotDriver()
        bot_driver.take_experiment()

        with tempfile.TemporaryDirectory() as tempdir:
            with pytest.raises(ValueError, match="must be one of"):
                ctx.invoke(export__local, path=tempdir, assets="asdasdoj")
            with pytest.raises(
                ValueError, match="asset selection 'all' has been removed"
            ):
                ctx.invoke(export__local, path=tempdir, assets="all")

            ctx.invoke(export__local, path=tempdir, assets="collected")

            self.assert_database_dir(os.path.join(tempdir, "database"))
            self.assert_identifier_sidecar(
                os.path.join(tempdir, "participant_identifiers.csv")
            )
            assert os.path.exists(os.path.join(tempdir, "manifest.json"))
            assert not os.path.exists(
                os.path.join(tempdir, "lucid_entrant_identifiers.csv")
            )
            assert not os.path.exists(os.path.join(tempdir, "data.zip"))
            assert not os.path.exists(os.path.join(tempdir, "database.zip"))

    def _test_asset_export_modes(self, ctx):
        import csv

        with tempfile.TemporaryDirectory() as tempdir:
            ctx.invoke(export__local, path=tempdir, assets="none")

            assert os.path.isdir(os.path.join(tempdir, "database"))
            assert not os.path.exists(os.path.join(tempdir, "assets"))
            assert not os.path.exists(os.path.join(tempdir, "data.zip"))

        with tempfile.TemporaryDirectory() as tempdir:
            ctx.invoke(export__local, path=tempdir, assets="collected")

            path = os.path.join(tempdir, "assets")
            assert os.path.exists(path) and os.path.isdir(path)
            assert os.path.exists(os.path.join(path, "manifest.csv"))
            assert not os.path.exists(os.path.join(path, "objects"))

            with open(os.path.join(path, "manifest.csv"), newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
            labels = {row["local_key"] for row in rows}
            assert "test_marked_asset" in labels
            assert "test_public_asset" in labels
            assert "test_external_asset" not in labels
            assert "test_on_demand_asset" not in labels
            for row in rows:
                export_path = row["export_path"]
                assert export_path
                assert os.path.exists(os.path.join(path, export_path))

    def assert_database_dir(self, path):
        import pandas as pd

        assert os.path.isdir(path)
        for name in ["participant.csv", "response.csv", "network.csv", "trial.csv"]:
            assert os.path.exists(os.path.join(path, name))

        asset_csv = pd.read_csv(os.path.join(path, "asset.csv"))
        assert asset_csv.shape[0] >= 2

        participant_csv = pd.read_csv(os.path.join(path, "participant.csv"))

        # Pseudonyms replace recruiter worker IDs inside the table CSVs.
        assert all(
            str(id_) == str(pid)
            for id_, pid in zip(participant_csv.worker_id, participant_csv.id)
        )

    def assert_identifier_sidecar(self, path):
        import pandas as pd

        sidecar = pd.read_csv(path)
        assert "participant_id" in sidecar.columns
        assert "worker_id" in sidecar.columns
        assert sidecar.shape[0] >= 1
        assert all(len(str(id_)) > 5 for id_ in sidecar.worker_id)
