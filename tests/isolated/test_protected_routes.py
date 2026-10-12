import pytest
import requests
from dallinger.utils import get_base_url

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_protected_routes(self):
        host = get_base_url()
        test_routes = [
            "/network/1",
            "/node/1/neighbors",
        ]
        for route in test_routes:
            with pytest.raises(requests.exceptions.ConnectionError) as excinfo:
                requests.get(host + route)
            assert (
                str(excinfo.value)
                == "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
            )
