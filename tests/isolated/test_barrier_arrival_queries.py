"""SQL budgets for last-arrival barrier checks and stacked finalize.

These tests pin statement counts on the post-commit coordination path, not
the full ``/timeline`` or ``/response`` stack. The numbers are a snapshot of
the current ORM path. The analysis, including which counts must stay
independent of group size, lives in
``docs/developer/sqlalchemy_performance.rst`` (Barrier last-arrival SQL
budgets). Fewer statements are an improvement: update the expected counts
here and in that section rather than treating a lower count as a failure to
preserve.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from dallinger import db
from flask import Flask

from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sqlalchemy_profiling import sqlalchemy_profile
from psynet.sync import (
    GroupBarrier,
    ParticipantLinkBarrier,
    SimpleGrouper,
    SimpleSyncGroup,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
    pending_arrival_notice_for,
)
from psynet.timeline import Timeline

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("consents")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]

# Precise snapshot of the current ORM path.
# Check = 19 + 2N (original 17 plus extra-connection lock_timeout, ORM
# lock_timeout, plus skip-after-commit lock_timeout + FOR UPDATE NOWAIT per
# waiter).
# Finalize = check + 6 overhead statements.
# Statement-by-statement analysis:
# docs/developer/sqlalchemy_performance.rst ("Barrier last-arrival SQL budgets").
# Lower counts are an improvement: update these constants and that section.
# Per-row writes still scale with group size; SQLAlchemy flushes them as one
# executemany statement per table, so UPDATE *statement* count stays 1.
_CHECK_BASE_QUERIES = 19
_SKIP_QUERIES_PER_WAITER = 2
_FINALIZE_OVERHEAD_QUERIES = 6


def _statement_count(profiler, pattern):
    compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    return sum(
        stat.count
        for stat in profiler.get_stats(top_n=None)
        if compiled.search(stat.statement)
    )


def _commit_count(profiler, *needles):
    """Count profiler commits whose callsite mentions any of ``needles``.

    Finalize's check ``session.commit()`` lives on
    ``_check_and_skip_held_instance``; the relock commit stays on
    ``_run_finalized_barrier_arrivals``. Count both so extracting the
    check helper does not look like a missing outer commit.
    """
    return sum(
        stat.count
        for stat in profiler.get_commit_stats(top_n=None)
        if any(needle in stat.callsite for needle in needles)
    )


def _budget(profiler):
    for_update = _statement_count(profiler, r"\bfor update\b")
    nowait = _statement_count(profiler, r"\bfor update\b.*\bnowait\b")
    return {
        "queries": profiler.total_count,
        "commits": profiler.commit_total_count,
        "nested_commits": _commit_count(
            profiler,
            "_run_pending_barrier_checks",
            "_check_and_skip_held_instance",
        ),
        "finalize_commits": _commit_count(
            profiler,
            "_run_finalized_barrier_arrivals",
            "_run_queued_barrier_checks",
        ),
        "for_update": for_update,
        "nowait": nowait,
        "relock_for_update": for_update - nowait,
        "advisory_try": _statement_count(profiler, r"pg_try_advisory_xact_lock"),
        "advisory_wait": _statement_count(profiler, r"SELECT pg_advisory_xact_lock\("),
        "spec_select": _statement_count(profiler, r"SELECT barrier_instance\.spec "),
        "savepoint": _statement_count(profiler, r"^SAVEPOINT "),
        "release_savepoint": _statement_count(profiler, r"^RELEASE SAVEPOINT "),
        "lock_timeout": _statement_count(profiler, r"set_config\('lock_timeout'"),
        "waiter_join": _statement_count(
            profiler,
            r"from participant_link_barrier join participant .*\bfor update\b.*\bnowait\b",
        ),
        "update_link": _statement_count(
            profiler, r"UPDATE participant_link_barrier SET"
        ),
        "update_hold_release": _statement_count(
            profiler, r"UPDATE timeline_hold SET released_at"
        ),
        "update_participant_wait": _statement_count(
            profiler, r"UPDATE participant SET time_credit"
        ),
        "sync_links_by_participant": _statement_count(
            profiler,
            r"FROM participant_link_sync_group WHERE .*participant_link_sync_group\.participant_id",
        ),
        "active_barriers_selectin": _statement_count(
            profiler,
            r"JOIN participant_link_barrier ON .*released = false WHERE participant_1\.id IN",
        ),
        "active_barriers_lazy": _statement_count(
            profiler,
            r"FROM participant_link_barrier WHERE .*participant_link_barrier\.participant_id"
            r".*released = false",
        ),
        "hold_by_pk": _statement_count(
            profiler, r"FROM timeline_hold WHERE timeline_hold\.id = "
        ),
        "hold_selectin": _statement_count(
            profiler, r"FROM timeline_hold WHERE timeline_hold\.id IN"
        ),
        "hold_wake_lookup": _statement_count(
            profiler, r"timeline_hold\.resumed_at IS NULL"
        ),
        "participant_pk": _statement_count(
            profiler, r"FROM participant LEFT OUTER JOIN trial"
        ),
    }


def _assert_budget(profiler, expected, *, label):
    actual = _budget(profiler)
    mismatches = {
        key: (actual[key], wanted)
        for key, wanted in expected.items()
        if actual[key] != wanted
    }
    if mismatches:
        raise AssertionError(
            f"{label}: unexpected SQL budget {mismatches}. "
            "If the new counts are an improvement, update the expected "
            "numbers here and docs/developer/sqlalchemy_performance.rst "
            "(Barrier last-arrival SQL budgets).\n"
            f"{profiler.format_summary(top_n=80, sort_by='count')}\n"
            f"{profiler.format_commit_summary()}"
        )


def _new_participant(experiment):
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id="XYZ",
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    return participant


def _sync_group_of(exp, db_session, n, group_type):
    participants = [_new_participant(exp) for _ in range(n)]
    for participant in participants:
        participant.status = "working"
    group = SimpleSyncGroup(
        group_type=group_type,
        initial_group_size=n,
        max_group_size=n,
        min_group_size=n,
        n_active_participants=n,
        accepts_top_ups=False,
    )
    db_session.add(group)
    for participant in participants:
        group.add_participant(participant)
    group.leader = participants[0]
    db_session.commit()
    return participants, group


def _arrive_at_group_barrier(exp, barrier, participant):
    barrier.receive_participant(participant)
    if barrier._uses_timeline_hold:
        barrier.waiting_logic.consume(exp, participant)


def _commit_barrier_arrivals():
    db.session.commit()
    checks = _take_pending_barrier_checks()
    if checks:
        _run_pending_barrier_checks(checks)
        db.session.commit()


def _queued_last_arrival_checks(exp, barrier, waiters, last):
    for waiter in waiters:
        _arrive_at_group_barrier(exp, barrier, waiter)
        _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)
    db.session.commit()
    return _take_pending_barrier_checks()


def _reset_experiment(experiment):
    """Drop instance timeline stubs left on the cached ``get_experiment()`` object."""
    experiment.timeline = type(experiment).timeline
    experiment.__dict__.pop("_advance_past_ready_holds", None)


@contextmanager
def _restored_experiment(experiment):
    original_timeline = experiment.timeline
    original_advance = experiment.__dict__.get("_advance_past_ready_holds")
    try:
        yield
    finally:
        experiment.timeline = original_timeline
        if original_advance is None:
            experiment.__dict__.pop("_advance_past_ready_holds", None)
        else:
            experiment._advance_past_ready_holds = original_advance


def _stub_finalize_timeline(experiment):
    page = SimpleNamespace(
        is_timeline_hold=False,
        pre_render=lambda: None,
        __json__=lambda participant: {"participant_id": participant.id},
    )
    experiment.timeline = SimpleNamespace(
        get_current_elt=lambda _experiment, _participant: page
    )
    experiment._advance_past_ready_holds = lambda participant, current_page: (
        current_page
    )
    return page


def _stacked_partner_timeline(group_type, group_size):
    return Timeline(
        SimpleGrouper(
            group_type=group_type,
            initial_group_size=group_size,
            content="Waiting for your partner",
        ),
        GroupBarrier(id_=f"{group_type}_init", group_type=group_type),
        GroupBarrier(id_=f"{group_type}_prepare", group_type=group_type),
        ModularPage("choose_action", "Choose your action", time_estimate=1),
    )


def _json_timeline(exp, participant):
    with Flask(__name__).test_request_context(
        f"/timeline?unique_id={participant.unique_id}",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return Experiment._route_timeline(exp, participant, mode="json")


def _check_expected(n):
    """Return the check-window snapshot for a group of size *n*.

    See docs/developer/sqlalchemy_performance.rst (Barrier last-arrival SQL
    budgets). Update both places if an improvement lowers these counts.
    """
    return {
        "queries": _CHECK_BASE_QUERIES + _SKIP_QUERIES_PER_WAITER * n,
        "commits": 2 + n,
        "nested_commits": 2,
        "for_update": 1 + n,
        "nowait": 1 + n,
        "relock_for_update": 0,
        "advisory_try": 1,
        "advisory_wait": 0,
        "spec_select": 1,
        "savepoint": 1,
        "release_savepoint": 1,
        "lock_timeout": 2 + n,
        "waiter_join": 1,
        "update_link": 1,
        "update_hold_release": 1,
        "update_participant_wait": 1,
        "sync_links_by_participant": 1,
        "active_barriers_selectin": 1,
        "active_barriers_lazy": 0,
        "hold_by_pk": 0,
        "hold_selectin": 1,
        "hold_wake_lookup": 0,
    }


def _finalize_expected(n):
    """Return the finalize-window snapshot: check plus six overhead statements.

    See docs/developer/sqlalchemy_performance.rst (Barrier last-arrival SQL
    budgets). Update both places if an improvement lowers these counts.
    """
    expected = _check_expected(n)
    expected.update(
        {
            "queries": expected["queries"] + _FINALIZE_OVERHEAD_QUERIES,
            "commits": expected["commits"] + 2,
            "finalize_commits": 2,
            "for_update": expected["for_update"] + 1,
            "relock_for_update": 1,
            "lock_timeout": expected["lock_timeout"] + 2,
            "active_barriers_lazy": 1,
        }
    )
    return expected


def _stacked_finalize_expected():
    """Return stacked last-arrival snapshot independent of skip-per-waiter growth.

    Last-arrival releases the filled visit and skips waiters after that commit.
    Pin the observed check/relock shape; update both places if it gets cheaper.
    See docs/developer/sqlalchemy_performance.rst (Barrier last-arrival SQL
    budgets).
    """
    return {
        "hold_wake_lookup": 0,
    }


def test_stacked_finalize_commit_and_lock_budget_does_not_grow_with_group_size(
    db_session, monkeypatch
):
    """Last-arrival stacked finalize skips waiters; lock kinds stay stable."""
    exp = get_experiment()
    _reset_experiment(exp)
    original_finalize = Experiment._finalize_barrier_arrivals
    captured = {}

    @classmethod
    def wrapped_finalize(cls, *args, **kwargs):
        with sqlalchemy_profile(db.engine) as profiler:
            out = original_finalize(*args, **kwargs)
            captured["profiler"] = profiler
            return out

    observed = {}
    with _restored_experiment(exp):
        try:
            for group_size in (2, 4):
                captured.clear()
                group_type = f"stack{group_size}_{uuid.uuid4().hex[:8]}"
                exp.timeline = _stacked_partner_timeline(group_type, group_size)
                participants = [_new_participant(exp) for _ in range(group_size)]
                for participant in participants:
                    participant.status = "working"
                db.session.commit()
                for waiter in participants[:-1]:
                    assert _json_timeline(exp, waiter).status_code == 200
                monkeypatch.setattr(
                    Experiment, "_finalize_barrier_arrivals", wrapped_finalize
                )
                last_response = _json_timeline(exp, participants[-1])
                monkeypatch.setattr(
                    Experiment, "_finalize_barrier_arrivals", original_finalize
                )
                assert last_response.status_code == 200
                profiler = captured["profiler"]
                _assert_budget(
                    profiler,
                    _stacked_finalize_expected(),
                    label=f"stacked_finalize n={group_size}",
                )
                observed[group_size] = _budget(profiler)
                last = Participant.query.get(participants[-1].id)
                last_page = exp.timeline.get_current_elt(exp, last)
                assert last.sync_group is not None
                assert last_page.label == "choose_action"
                for waiter in participants[:-1]:
                    waiter = Participant.query.get(waiter.id)
                    page = exp.timeline.get_current_elt(exp, waiter)
                    assert not getattr(page, "is_timeline_hold", False)
                    assert page.label == "choose_action"
        finally:
            monkeypatch.setattr(
                Experiment, "_finalize_barrier_arrivals", original_finalize
            )

    for key in (
        "advisory_try",
        "advisory_wait",
        "spec_select",
        "waiter_join",
    ):
        assert observed[2][key] == observed[4][key]
    # Evaluating the filled visit still loads per-waiter rows as group size
    # grows, and skip-after-commit walks each waiter. A smaller delta is an
    # improvement.
    extra_members = 2
    query_delta = observed[4]["queries"] - observed[2]["queries"]
    assert query_delta >= 0
    # Skip-after-commit walks each extra member through the stack
    # (grouper + two GroupBarriers). A smaller delta is an improvement.
    assert query_delta <= 80 * extra_members


def test_check_instance_sql_matches_waiter_formula(db_session):
    """Last-arrival checks stay O(1) in statement kinds; skip grows with *N*."""
    exp = get_experiment()
    _reset_experiment(exp)
    observed = {}
    for n in (2, 8):
        participants, _group = _sync_group_of(exp, db_session, n, group_type=f"q{n}")
        waiters, last = participants[:-1], participants[-1]
        barrier = GroupBarrier(
            id_=f"gate_{n}_{uuid.uuid4().hex[:8]}", group_type=f"q{n}"
        )
        checks = _queued_last_arrival_checks(exp, barrier, waiters, last)
        db.session.expire_all()
        with sqlalchemy_profile(db.engine) as profiler:
            assert _run_pending_barrier_checks(checks) is True
        released = (
            db_session.query(ParticipantLinkBarrier)
            .filter_by(barrier_id=barrier.id, released=True)
            .count()
        )
        assert released == n
        observed[n] = _budget(profiler)
        _assert_budget(profiler, _check_expected(n), label=f"check n={n}")

    for key in (
        "spec_select",
        "waiter_join",
        "savepoint",
        "sync_links_by_participant",
        "active_barriers_selectin",
        "hold_selectin",
        "update_link",
        "update_hold_release",
        "update_participant_wait",
    ):
        assert observed[2][key] == observed[8][key] == 1
    assert observed[2]["advisory_try"] == observed[8]["advisory_try"] == 1
    assert observed[2]["advisory_wait"] == observed[8]["advisory_wait"] == 0
    assert observed[2]["queries"] == _CHECK_BASE_QUERIES + _SKIP_QUERIES_PER_WAITER * 2
    assert observed[8]["queries"] == _CHECK_BASE_QUERIES + _SKIP_QUERIES_PER_WAITER * 8
    assert observed[2]["nowait"] == 3
    assert observed[8]["nowait"] == 9
    assert observed[2]["hold_wake_lookup"] == observed[8]["hold_wake_lookup"] == 0


def test_finalize_commits_check_then_relock_independent_of_group_size(db_session):
    """Check kinds stay O(1); skip-after-commit and commits grow with *N*."""
    exp = get_experiment()
    _reset_experiment(exp)
    observed = {}
    for n in (2, 8):
        participants, _group = _sync_group_of(exp, db_session, n, group_type=f"f{n}")
        waiters, last = participants[:-1], participants[-1]
        barrier = GroupBarrier(
            id_=f"fin_{n}_{uuid.uuid4().hex[:8]}", group_type=f"f{n}"
        )
        checks = _queued_last_arrival_checks(exp, barrier, waiters, last)
        result = SimpleNamespace(page=None, payload={})
        db.session.expire_all()
        with _restored_experiment(exp):
            page = _stub_finalize_timeline(exp)
            with sqlalchemy_profile(db.engine) as profiler:
                Experiment._finalize_barrier_arrivals(exp, last.id, checks, result)
        _assert_budget(profiler, _finalize_expected(n), label=f"finalize n={n}")
        assert result.page is page
        observed[n] = _budget(profiler)

    for key in (
        "nested_commits",
        "spec_select",
        "advisory_try",
        "advisory_wait",
    ):
        assert observed[2][key] == observed[8][key]


def test_pending_arrival_notice_reconstructs_each_instance_once(db_session):
    """Partner-ready notices must not reconstruct the same instance per waiter."""
    exp = get_experiment()
    _reset_experiment(exp)
    n = 8
    participants, _group = _sync_group_of(exp, db_session, n, group_type="notice")
    waiters, last = participants[:-1], participants[-1]
    barrier = GroupBarrier(
        id_=f"notice_{uuid.uuid4().hex[:8]}",
        group_type="notice",
        notify_arrivals=True,
    )
    for waiter in waiters:
        _arrive_at_group_barrier(exp, barrier, waiter)
        _commit_barrier_arrivals()
    db.session.commit()
    db.session.expire_all()
    last = Participant.query.get(last.id)
    with sqlalchemy_profile(db.engine) as profiler:
        notice = pending_arrival_notice_for(last)
    assert notice
    # 5 + 3(N-1): see docs/developer/sqlalchemy_performance.rst
    # (Barrier last-arrival SQL budgets). Update both if this gets cheaper.
    _assert_budget(
        profiler,
        {
            "queries": 5 + 3 * (n - 1),
            "commits": 0,
            "for_update": 0,
            "spec_select": 1,
            "active_barriers_lazy": n - 1,
            "participant_pk": n - 1,
        },
        label="pending_arrival_notice n=8",
    )
