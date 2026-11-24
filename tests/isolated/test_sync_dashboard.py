import uuid
from datetime import datetime

import pytest
import requests

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_demo_feature
from psynet.sync import SimpleSyncGroup
from psynet.utils import get_authenticated_session


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_feature("group_closer")],
    indirect=True,
)
def test_dashboard_renders_sync_groups_and_protects_sensitive_requests(
    launched_experiment, db_session
):
    group = SimpleSyncGroup(
        group_type="empty-leader",
        initial_group_size=1,
        max_group_size=1,
        quorum=1,
        n_active_participants=0,
        accepts_top_ups=True,
    )
    db_session.add(group)
    db_session.commit()

    session = get_authenticated_session(launched_experiment.base_url)
    response = session.get(f"{launched_experiment.base_url}/dashboard/sync_groups")
    response.raise_for_status()

    assert "PNone" not in response.text
    assert "—" in _row(response.text, "empty-leader")

    participant = _participant()
    group = SimpleSyncGroup(
        group_type="dashboard-actions",
        initial_group_size=1,
        max_group_size=2,
        quorum=1,
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
    # Experiment status artifacts can contain the credential-bearing basic data URL.
    assert (
        unauthenticated_session.get(
            f"{launched_experiment.base_url}/dashboard/status/get",
            params={
                "deployment_id": "deployment-1",
                "type": "experiment",
            },
        ).status_code
        == 401
    )
    assert (
        unauthenticated_session.post(
            f"{action_url}/fail", data={"fail_reason": "manual_failure"}
        ).status_code
        == 401
    )

    response = session.post(
        f"{action_url}/fail", data={"fail_reason": "manual_failure"}
    )
    response.raise_for_status()
    assert response.json()["status"] == "success"
    db_session.expire_all()
    assert participant.failed
    assert participant not in SimpleSyncGroup.query.get(group.id).active_participants

    finishers, groups = {}, {}
    for group_type, accepts_top_ups in [
        ("finished", False),
        ("open", True),
        ("pending", False),
    ]:
        finisher = _participant()
        finisher.elt_id = ["successful_end", 0]
        group = SimpleSyncGroup(
            group_type=f"{group_type}-group",
            initial_group_size=1,
            max_group_size=2,
            quorum=1,
            n_active_participants=1,
            accepts_top_ups=accepts_top_ups,
        )
        db_session.add_all([finisher, group])
        db_session.flush()
        group.add_participant(finisher)
        finishers[group_type], groups[group_type] = finisher, group
    finishers["finished"].end_time = datetime(2026, 1, 2, 3, 4, 5)
    leaver = _participant()
    db_session.add(leaver)
    db_session.flush()
    groups["finished"].add_participant(leaver)
    groups["finished"].remove_participant(leaver, reason="late")
    newcomer = _participant()
    db_session.add(newcomer)
    db_session.flush()
    groups["pending"]._add_link(newcomer, admitted=False)
    dissolved = SimpleSyncGroup(
        group_type="dissolved-group",
        initial_group_size=2,
        max_group_size=2,
        quorum=2,
        active=False,
        accepts_top_ups=True,
    )
    db_session.add(dissolved)
    db_session.commit()

    page = session.get(f"{launched_experiment.base_url}/dashboard/sync_groups").text
    assert (
        "Left group: left_experiment. Status: working. Failed: manual_failure"
        in _row(page, "dashboard-actions")
    )
    finished_row = _row(page, "finished-group")
    assert "Finished" in finished_row
    assert "<strong>0</strong>" in finished_row
    assert f">{finishers['finished'].id}</span>" in finished_row
    assert "2026-01-02 03:04:05" in finished_row
    pending_row = _row(page, "pending-group")
    assert "Active" in pending_row
    assert "<strong>0</strong>" in pending_row
    open_row = _row(page, "open-group")
    assert "Active" in open_row
    assert "Accepts top-ups" in open_row
    dissolved_row = _row(page, "dissolved-group")
    assert "Closed" in dissolved_row
    assert "Accepts top-ups" not in dissolved_row


def _participant():
    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id="XYZ",
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    participant.status = "working"
    return participant


def _row(page, group_type):
    """Return the dashboard table row of the group of ``group_type``."""
    start = page.index(f"<td>{group_type}</td>")
    return page[start : page.index("</tr>", start)]
