"""Dashboard network monitor includes PsyNet trials after Trial left Info."""

import json
import re

import pytest

from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.main import Trial
from psynet.utils import get_authenticated_session


def _network_structure_from_monitoring_html(html: str) -> dict:
    match = re.search(
        r"const network_structure = (\{.*?\});\s*",
        html,
        flags=re.DOTALL,
    )
    assert match is not None, (
        "network_structure assignment missing from monitoring page"
    )
    return json.loads(match.group(1))


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_dashboard_monitoring_includes_trials_as_infos(launched_experiment, trial):
    """HTTP monitoring page serializes trials into the Dallinger infos slot."""
    assert Trial.query.count() >= 1

    structure = launched_experiment.network_structure()
    assert structure["infos"], "expected trials in network_structure infos slot"
    matched = [row for row in structure["infos"] if row.get("id") == trial.id]
    assert len(matched) == 1
    assert matched[0]["origin_id"] == trial.node_id
    assert matched[0]["node_id"] == trial.node_id
    assert matched[0]["object_type"] == "Trial"

    session = get_authenticated_session(launched_experiment.base_url)
    response = session.get(f"{launched_experiment.base_url}/dashboard/monitoring")
    assert response.status_code == 200
    assert "KeyError" not in response.text
    assert "Experiment Monitoring" in response.text

    page_structure = _network_structure_from_monitoring_html(response.text)
    page_matched = [row for row in page_structure["infos"] if row.get("id") == trial.id]
    assert len(page_matched) == 1
    assert page_matched[0]["origin_id"] == trial.node_id
    assert page_matched[0]["object_type"] == "Trial"
