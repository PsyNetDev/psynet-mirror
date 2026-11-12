"""Audit of the barrier poller's batched peek, autouse for every isolated test via ``conftest.py``.

Each visit the peek says needs no check is checked at once, and its row, its
waiters, and their groups and members must come out unchanged; otherwise
:meth:`psynet.sync.Barrier.needs_check` missed a change the check makes. The
audit also checks those visits at every sweep, as before the peek, so tests
of when the poller ends a wait, and tests that count a sweep's statements,
turn it off with :func:`unaudited`.
"""

import pytest
from dallinger import db
from sqlalchemy import text
from sqlalchemy.orm import Session

import psynet.sync

_PEEK = psynet.sync._visits_that_need_checks


def unaudited(monkeypatch):
    """Let the poller's sweeps skip the audit for the rest of the test."""
    monkeypatch.setattr(psynet.sync, "_visits_that_need_checks", _PEEK)


def _visit_state(instance_id):
    """Return a visit's row, who waits there, and the waiters' groups with their members, read in a fresh session."""
    waiters_groups = (
        "SELECT g.sync_group_id FROM participant_link_sync_group g"
        " JOIN participant_link_barrier l ON l.participant_id = g.participant_id"
        " WHERE l.barrier_instance_id = :id AND NOT l.released AND g.active"
    )
    queries = [
        "SELECT * FROM barrier_instance WHERE id = :id",
        "SELECT l.participant_id FROM participant_link_barrier l "
        "JOIN participant p ON p.id = l.participant_id "
        "WHERE l.barrier_instance_id = :id AND NOT l.released "
        "AND NOT p.failed AND p.status = 'working' ORDER BY 1",
        "SELECT m.participant_id, m.sync_group_id, p.failed, p.status "
        "FROM participant_link_sync_group m "
        "JOIN participant p ON p.id = m.participant_id "
        f"WHERE m.active AND m.sync_group_id IN ({waiters_groups}) ORDER BY 1, 2",
        f"SELECT * FROM sync_group WHERE id IN ({waiters_groups}) ORDER BY id",
    ]
    with Session(bind=db.engine) as session:
        return [
            session.execute(text(query), {"id": instance_id}).all() for query in queries
        ]


@pytest.fixture(autouse=True)
def _audit_needs_check(monkeypatch):
    """Fail the test if the poller passes over a visit whose check would change it."""
    failures = []

    def audited(instance_ids):
        need_checks = _PEEK(instance_ids)
        for instance_id in sorted(set(instance_ids) - need_checks):
            before = _visit_state(instance_id)
            if psynet.sync._process_barrier_instance(instance_id):
                continue
            if _visit_state(instance_id) != before:
                failures.append(
                    f"The poller passed over barrier visit {instance_id}, but its "
                    "check changed it: needs_check() misses something."
                )
        return need_checks

    monkeypatch.setattr(psynet.sync, "_visits_that_need_checks", audited)
    yield
    assert not failures, failures
