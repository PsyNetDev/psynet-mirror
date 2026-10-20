import zipfile

import pytest

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_remote_launch_prepares_without_touching_the_local_database():
    """A remote launch builds its database template in a scratch database."""
    from dallinger import db
    from dallinger.models import Network

    from psynet import deployment_info
    from psynet.command_line import _prepare_in_scratch_database
    from psynet.experiment import database_template_path

    deployment_info.init(
        redeploying_from_archive=False,
        mode="sandbox",
        is_local_deployment=False,
        is_ssh_deployment=True,
        server="",
        app="",
    )
    db.init_db(drop_all=True)
    db.session.add(Network(role="local-data"))
    db.session.commit()

    _prepare_in_scratch_database(archive=None)

    db.session.remove()
    assert Network.query.filter_by(role="local-data").count() == 1
    with zipfile.ZipFile(database_template_path) as template:
        assert "data/experiment.csv" in template.namelist()
        assert b"local-data" not in template.read("data/network.csv")
