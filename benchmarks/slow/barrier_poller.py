"""
ASV benchmark for the barrier poller's idle sweep as waiting visits grow.

An idle ``check_barriers`` sweep reads every waiting visit in a fixed number
of statements, so its time should grow about linearly with the visits.
``setup_cache`` runs ``tests/isolated/barrier_sweep_benchmark.py`` with
pytest, which gives it an experiment and a database, and the ``track_*``
methods report its median sweep time and statement count. The statement
count is pinned by ``tests/isolated/test_group_request_queries.py``; this
benchmark tracks the time, which can grow without new statements (for
example when the sweep loads more columns or a query plan changes).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class IdleBarrierSweep:
    """
    Idle ``check_barriers`` sweeps over pairs waiting for a late partner.

    Attributes
    ----------

    params : list[list[int]]
        Numbers of waiting visits to measure.

    timeout : int
        Hard upper bound (seconds) for ``setup_cache``.
    """

    params = [[100, 300]]
    param_names = ["waiting_visits"]
    timeout = 900

    # See ``experiment_performance._BaseExperiment.version``.
    version = 1

    def setup_cache(self):
        repo_root = Path(__file__).parents[2]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output = Path(f.name)
        try:
            subprocess.run(
                [
                    sys.executable,
                    # Keep the checkout's psynet/ off sys.path, so the
                    # commit ASV installed is the one measured.
                    "-P",
                    "-m",
                    "pytest",
                    "tests/isolated/barrier_sweep_benchmark.py",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=repo_root,
                env={
                    **os.environ,
                    "WAITING_VISITS": ",".join(map(str, self.params[0])),
                    "BARRIER_SWEEP_OUTPUT": str(output),
                },
                check=True,
            )
            return {int(n): r for n, r in json.loads(output.read_text()).items()}
        finally:
            output.unlink(missing_ok=True)

    def track_sweep_time_ms(self, results, waiting_visits):
        return results[waiting_visits]["sweep_ms"]

    track_sweep_time_ms.unit = "ms"
    track_sweep_time_ms.pretty_name = "idle barrier sweep time"

    def track_sweep_statements(self, results, waiting_visits):
        return results[waiting_visits]["statements"]

    track_sweep_statements.unit = "statements"
    track_sweep_statements.pretty_name = "idle barrier sweep statements"
