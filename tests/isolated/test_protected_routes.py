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
            "/participant/1",
        ]
        for route in test_routes:
            with pytest.raises(requests.exceptions.ConnectionError) as excinfo:
                requests.get(host + route)
            assert (
                str(excinfo.value)
                == "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
            )

    def test_recruiter_exit_requires_the_participants_unique_id(self):
        host = get_base_url()
        participant = requests.post(
            host + "/participant/exit-worker/exit-hit/exit-assignment/debug"
        ).json()["participant"]
        other = requests.post(
            host + "/participant/other-worker/exit-hit/other-assignment/debug"
        ).json()["participant"]
        exit_url = host + "/recruiter-exit"
        participant_id = participant["id"]

        for params in (
            {"participant_id": participant_id},
            {"participant_id": participant_id, "unique_id": other["unique_id"]},
        ):
            response = requests.get(exit_url, params=params)
            assert response.status_code == 403
            assert "exit-assignment" not in response.text

        error_page = requests.get(
            host + "/error-page", params={"participant_id": participant_id}
        )
        assert "exit-assignment" not in error_page.text

        response = requests.get(
            exit_url,
            params={
                "participant_id": participant_id,
                "unique_id": participant["unique_id"],
            },
        )
        assert response.status_code == 200
        assert "exit-assignment" in response.text
