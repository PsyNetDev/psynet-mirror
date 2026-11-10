"""SQL budgets for grouped participant requests, leaving or dissolving a group, and the pollers.

``test_barrier_arrival_queries`` pins the post-commit barrier check. These
tests drive real ``/timeline`` and ``/response`` requests from a cold session
to form a group, then pin the requests around the barrier (arriving from a
page and the hold poll while waiting), what it costs for a member to leave,
for a group to dissolve, and for one idle sweep of each poller. Arriving and
leaving compare two group sizes, so a statement that runs once per member
fails; dissolving and the sweeps pin their per-member or per-group slope. Fewer statements are an
improvement: lower the numbers here and in
``docs/developer/sqlalchemy_performance.rst`` (Grouped request budgets).
"""

import json
import sys
from pathlib import Path

import pytest
from dallinger import db
from flask import Flask

from psynet import sync
from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sqlalchemy_profiling import sqlalchemy_profile
from psynet.sync import GroupBarrier, ParticipantLinkBarrier, SimpleGrouper
from psynet.timeline import Timeline

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_hold_helpers import _working_participants  # noqa: E402

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory", [path_to_test_experiment("consents")], indirect=True
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]

_APP = Flask(__name__)

# A request commits several times, and rows it drops from the weak identity
# map in between are loaded again on next use. That moves a count by a
# statement or two between runs; a statement per member adds at least four.
_JITTER = 2

# Ceiling: dissolving fails each remaining member with their own loads, lock
# refresh, trial lock, hold lookup and flushes (about 10 each). Lower is better.
_DISSOLVE_PER_MEMBER = 14

# Snapshot: each sweep fully re-checks every waiting visit and recounts every
# active group, even when nothing changed (including the deferred
# ``below_quorum_since`` load in ``SimpleSyncGroup.check_numbers``). Lower is
# better.
_SWEEP_PER_VISIT = 19
_SYNC_GROUPS_PER_GROUP = 7


def _timeline(group_size, quorum=None):
    return Timeline(
        SimpleGrouper(
            "room",
            initial_group_size=group_size,
            quorum=quorum or group_size,
        ),
        ModularPage("choose", "Choose", PushButtonControl(["a", "b"]), time_estimate=1),
        GroupBarrier(id_="room_gate", group_type="room"),
        ModularPage("result", "Result", time_estimate=1),
    )


def _get(participant_id):
    db.session.remove()
    unique_id = Participant.query.get(participant_id).unique_id
    db.session.remove()
    with _APP.test_request_context(
        f"/timeline?unique_id={unique_id}&mode=json",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert Experiment.route_timeline().status_code == 200


def _post(participant_id, raw_answer=None, *, resume=False):
    db.session.remove()
    page_uuid = Participant.query.get(participant_id).page_uuid
    db.session.remove()
    payload = {
        "participant_id": participant_id,
        "page_uuid": page_uuid,
        "raw_answer": raw_answer,
        "metadata": {"time_taken": 1},
        "include_timeline_fragment": False,
        "timeline_hold_resume": resume,
    }
    with _APP.test_request_context(
        "/response",
        method="POST",
        data={"json": json.dumps(payload)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert Experiment.route_response().status_code == 200


def _fail(participant_id):
    participant = (
        get_experiment()
        ._participant_request_query()
        .with_for_update(of=Participant)
        .populate_existing()
        .get(participant_id)
    )
    participant.fail("left")
    db.session.commit()


def _count(fn):
    db.session.remove()
    with sqlalchemy_profile(db.engine) as profiler:
        fn()
    db.session.remove()
    return profiler.total_count


def _released_count(barrier_id):
    db.session.remove()
    return ParticipantLinkBarrier.query.filter_by(
        barrier_id=barrier_id, released=True
    ).count()


def _group_on_choose_page(exp, group_size):
    """Form a group through real requests; everyone ends on the choose page."""
    ids = [p.id for p in _working_participants(exp, group_size)]
    for participant_id in ids:
        _get(participant_id)
    for participant_id in ids[:-1]:
        _post(participant_id, resume=True)
    return ids


@pytest.fixture
def exp(db_session, deployment_info, monkeypatch):
    experiment = get_experiment()
    monkeypatch.setattr(
        experiment.pseudonym_scheme, "_deployment_seed", "budget", raising=False
    )
    original = experiment.timeline
    yield experiment
    experiment.timeline = original


def test_leaving_a_group_does_not_load_every_member(exp):
    """The leader failing leaves a group above quorum in the same statements for 4 and 8."""
    counts = {}
    for group_size in (4, 8):
        db.session.remove()
        exp.timeline = _timeline(group_size, quorum=2)
        ids = _group_on_choose_page(exp, group_size)
        leader_id = Participant.query.get(ids[0]).sync_group.leader_id
        counts[group_size] = _count(lambda: _fail(leader_id))
    assert counts[8] <= counts[4] + _JITTER, counts


def test_dissolving_a_group_costs_a_fixed_amount_per_member(exp):
    """A member failing below quorum dissolves the group at a pinned cost per member."""
    counts = {}
    for group_size in (4, 8):
        db.session.remove()
        exp.timeline = _timeline(group_size)
        ids = _group_on_choose_page(exp, group_size)
        counts[group_size] = _count(lambda: _fail(ids[-1]))
        failed = Participant.query.filter(Participant.id.in_(ids), Participant.failed)
        assert failed.count() == group_size
    assert all(
        count <= _DISSOLVE_PER_MEMBER * size for size, count in counts.items()
    ), counts


def test_poller_sweeps_cost_a_fixed_amount_per_group(exp, monkeypatch):
    """Idle sweeps of check_barriers and check_sync_groups scale with groups, not members."""
    monkeypatch.setattr(sync, "_POLLER_SWEEP_BUDGET_SECONDS", 60)
    exp.timeline = _timeline(2)
    barriers, groups = {}, {}
    for n_groups, new_groups in ((1, 1), (3, 2)):
        for _ in range(new_groups):
            ids = _group_on_choose_page(exp, 2)
            _post(ids[0], "a")
        sync.check_barriers()
        barriers[n_groups] = _count(sync.check_barriers)
        groups[n_groups] = _count(sync.check_sync_groups)
    assert barriers[3] - barriers[1] == 2 * _SWEEP_PER_VISIT, barriers
    assert groups[3] - groups[1] == 2 * _SYNC_GROUPS_PER_GROUP, groups


def test_barrier_requests_do_not_grow_with_group_size(exp):
    """Arriving from a page, polling the hold and the last arrival cost the same for 3 and 7."""
    counts = {}
    for group_size in (3, 7):
        db.session.remove()
        group_type = f"room{group_size}"
        barrier_id = f"{group_type}_gate"
        # No hold timeouts, so slow profiled requests cannot dissolve the group.
        exp.timeline = Timeline(
            SimpleGrouper(
                group_type, initial_group_size=group_size, max_wait_time=None
            ),
            ModularPage(
                "choose", "Choose", PushButtonControl(["a", "b"]), time_estimate=1
            ),
            GroupBarrier(id_=barrier_id, group_type=group_type, max_wait_time=None),
            ModularPage("result", "Result", time_estimate=1),
        )
        ids = [p.id for p in _working_participants(exp, group_size)]
        for participant_id in ids:
            _get(participant_id)
        for participant_id in ids[:-1]:
            _post(participant_id, resume=True)
        for participant_id in ids[:-2]:
            _post(participant_id, "a")
        counts[group_size] = {
            "arrival_post": _count(lambda: _post(ids[-2], "a")),
            "hold_poll_post": _count(lambda: _post(ids[0], resume=True)),
        }
        assert _released_count(barrier_id) == 0
        counts[group_size]["last_arrival_post"] = _count(lambda: _post(ids[-1], "a"))
        assert _released_count(barrier_id) == group_size
        assert not any(Participant.query.get(i).failed for i in ids)
        counts[group_size]["released_poll_post"] = _count(
            lambda: _post(ids[0], resume=True)
        )
    grown = {
        key: (counts[3][key], counts[7][key])
        for key in counts[3]
        if counts[7][key] > counts[3][key] + _JITTER
    }
    assert not grown, f"grew with group size: {grown}; all counts: {counts}"
