"""Measure idle check_barriers sweeps for ``benchmarks/slow/barrier_poller.py``.

Not collected by the test suite (the name doesn't start with ``test_``). The
ASV benchmark runs it with pytest, for the experiment and database fixtures,
and passes the visit counts and the output path in the environment. It runs
against whichever PsyNet ASV installed, so it may only use names that exist
on the benchmark's baseline commit too.
"""

import json
import os
import statistics
import sys
import time
from pathlib import Path

import pytest
from dallinger import db

from psynet import sync
from psynet.experiment import get_experiment
from psynet.sqlalchemy_profiling import sqlalchemy_profile
from psynet.sync import GroupBarrier, SimpleGrouper

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_hold_helpers import _working_participants  # noqa: E402

_SWEEPS = 7


@pytest.mark.parametrize(
    "experiment_directory",
    [str(Path(__file__).resolve().parents[1] / "experiments" / "consents")],
    indirect=True,
)
def test_measure_idle_sweeps(
    in_experiment_directory, db_session, deployment_info, monkeypatch
):
    """Time idle sweeps over pairs waiting at a GroupBarrier for a late partner."""
    monkeypatch.setattr(sync, "_POLLER_SWEEP_BUDGET_SECONDS", 600)
    exp = get_experiment()
    grouper = SimpleGrouper("main", initial_group_size=2)
    barrier = GroupBarrier(
        id_="slow_partner", group_type="main", late_after=3600, late_action="fail"
    )
    results = {}
    for n_visits in sorted(int(n) for n in os.environ["WAITING_VISITS"].split(",")):
        while len(sync._waiting_barrier_instance_ids()) < n_visits:
            pair = _working_participants(exp, 2)
            grouper._make_group(pair, initial_group_size=2)
            db.session.commit()
            barrier.receive_participant(pair[0])
            if barrier._uses_timeline_hold:
                barrier.waiting_logic.consume(exp, pair[0])
            db.session.commit()
        sync.check_barriers()
        durations = []
        for _ in range(_SWEEPS):
            db.session.remove()
            start = time.perf_counter()
            with sqlalchemy_profile(db.engine) as profiler:
                sync.check_barriers()
            durations.append(time.perf_counter() - start)
        results[n_visits] = {
            "sweep_ms": 1000 * statistics.median(durations),
            "statements": profiler.total_count,
        }
    Path(os.environ["BARRIER_SWEEP_OUTPUT"]).write_text(json.dumps(results))
