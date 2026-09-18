import uuid

import pytest
import requests

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.sync import SimpleSyncGroup
from psynet.utils import get_authenticated_session


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_experiment("simple_sync_group")],
    indirect=True,
)
def test_sync_groups_dashboard_renders_empty_leader_as_placeholder(
    launched_experiment, db_session
):
    group = SimpleSyncGroup(
        group_type="empty-leader",
        initial_group_size=1,
        max_group_size=1,
        min_group_size=1,
        n_active_participants=0,
        accepts_top_ups=True,
    )
    db_session.add(group)
    db_session.commit()

    session = get_authenticated_session(launched_experiment.base_url)
    response = session.get(f"{launched_experiment.base_url}/dashboard/sync_groups")
    response.raise_for_status()

    row_start = response.text.index("<td>empty-leader</td>")
    empty_leader_row = response.text[
        row_start : response.text.index("</tr>", row_start)
    ]
    assert "PNone" not in response.text
    assert "—" in empty_leader_row

    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id="XYZ",
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    participant.status = "working"
    group = SimpleSyncGroup(
        group_type="dashboard-actions",
        initial_group_size=1,
        max_group_size=2,
        min_group_size=1,
        n_active_participants=1,
        accepts_top_ups=True,
    )
    db_session.add_all([participant, group])
    group.add_participant(participant)
    group.leader = participant
    db_session.commit()

    action_url = (
        f"{launched_experiment.base_url}/dashboard/sync-groups/{group.id}"
        f"/participant/{participant.id}"
    )
    unauthenticated_session = requests.Session()
    assert (
        unauthenticated_session.post(
            f"{action_url}/fail", data={"fail_reason": "manual_failure"}
        ).status_code
        == 401
    )
    assert (
        unauthenticated_session.post(
            f"{action_url}/kick", data={"kick_reason": "manual_kick"}
        ).status_code
        == 401
    )

    response = session.post(f"{action_url}/kick", data={"kick_reason": "manual_kick"})
    response.raise_for_status()
    assert response.json()["status"] == "success"
    db_session.expire_all()
    assert participant not in SimpleSyncGroup.query.get(group.id).active_participants
