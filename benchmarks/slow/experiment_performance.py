"""
ASV benchmarks for end-to-end experiment performance.

ASV discovers benchmark classes in this module via ``benchmark_dir`` in
``asv.conf.json``, and calls two kinds of methods:

- ``setup_cache()``: called once per class, runs all parameter combinations
  and returns a dict of results. ASV passes this dict as the first argument
  to every ``track_*`` call. Each subclass must define its own ``setup_cache``
  (even as a one-line ``return super().setup_cache()``); ASV keys the cache
  by ``(module, source line of the method)``, so an inherited method causes
  ASV to share one cached result across every subclass.
- ``track_*(data, *param_values)``: called once per parameter combination,
  extracts a single scalar metric from the cached results.

See https://asv.readthedocs.io/en/stable/writing_benchmarks.html
"""

import itertools
import json
import subprocess
import tempfile
import types
from pathlib import Path


class _BaseExperiment:
    """
    Base class for end-to-end performance benchmarks of a single psynet demo.

    ``setup_cache`` invokes ``psynet performance-test local`` for each
    combination of ``params`` and stores the per-combination output in a dict
    keyed by parameter tuple (in ``param_names`` order). ``track_*`` methods
    then extract scalar metrics such as median request time or queue delay per
    combination. Subclasses must set ``demo_name``; everything else has sensible
    defaults.

    Sweep axes (``param_names``) map to ``psynet performance-test local`` CLI
    flags by replacing underscores with dashes (e.g. ``"duration_minutes"`` ->
    ``--duration-minutes``); any flag the CLI accepts is sweepable. Values not
    specified take the CLI default. Each Cartesian combination triggers one
    psynet invocation.

    Attributes
    ----------

    demo_name : str
        Directory name of the demo under ``demo_root``. Required.

    demo_root : str
        Path (relative to the repo root) of the demo tree containing
        ``demo_name``. Defaults to ``"demos/experiments"``; override to
        ``"tests/experiments"`` for fixture demos.

    params : list[list]
        ASV-style sweep, one inner list per axis. ``asv`` benchmarks every
        combination, producing one row per combination per ``track_*`` method.
        Defaults to a single 2-minute test with a bot-count of 10: ``[[10],
        [2.0]]``. To sweep multiple bot counts: ``[[10, 25, 50], [2.0]]``. To also
        sweep duration: ``[[25], [1.0, 2.0]]`` (with ``param_names = ["n_bots",
        "duration_minutes"]``).

    param_names : list[str]
        Names for each axis of ``params``, in matching order. Each name is
        passed through to the corresponding ``psynet performance-test local``
        CLI flag (underscores → dashes). Defaults to ``["n_bots",
        "duration_minutes"]``. Track methods receive the per-combination values
        positionally via ``*param_values`` after the cached data.

    timeout : int
        Hard upper bound (seconds) for ``setup_cache`` before asv kills the run.
        Should accommodate the full Cartesian sweep, since ``setup_cache`` runs
        every combination before any ``track_*`` call. Defaults to ``1800``.
    """

    demo_name: str | None = None
    demo_root = "demos/experiments"
    params = [[10], [2.0]]
    param_names = ["n_bots", "duration_minutes"]
    timeout = 1800

    # Explicit benchmark version. Without this ASV uses a hash of the benchmark
    # source, and silently drops historical results whose stored hash no longer
    # matches -- so cosmetic changes wipe the history. Pins version to allow
    # refactors that shouldn't impact performance. Bump this integer when a
    # benchmark change makes new results incomparable to old ones.
    version = 5

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Prefix each base-class track_* method's pretty_name with demo_name so
        # the rendered ASV table distinguishes per-demo rows at a glance. The
        # base track_* methods are shared function objects, so the prefix has
        # to go on a per-subclass clone -- mutating the shared object in place
        # would clobber the other subclasses. A track_* the subclass defines
        # itself is left alone (its own pretty_name stands), as is any base
        # track_* without a pretty_name (ASV falls back to its name).
        for attr, base_method in vars(_BaseExperiment).items():
            if not attr.startswith("track_") or attr in cls.__dict__:
                continue
            base_pretty = getattr(base_method, "pretty_name", None)
            if base_pretty is None:
                continue
            clone = types.FunctionType(base_method.__code__, base_method.__globals__)
            clone.__dict__.update(base_method.__dict__)
            clone.pretty_name = f"{cls.demo_name} {base_pretty}"
            setattr(cls, attr, clone)

    def setup_cache(self):
        if self.demo_name is None:
            raise NotImplementedError("subclass must set demo_name")

        repo_root = Path(__file__).parents[2]
        demo_dir = repo_root / self.demo_root / self.demo_name

        results = {}
        for combo in itertools.product(*self.params):
            flags = []
            for name, value in zip(self.param_names, combo):
                flags += [f"--{name.replace('_', '-')}", str(value)]

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                json_path = f.name

            try:
                subprocess.run(
                    [
                        "psynet",
                        "performance-test",
                        "local",
                        *flags,
                        "--json-output",
                        str(json_path),
                    ],
                    cwd=demo_dir,
                    check=True,
                )
                try:
                    with open(json_path) as fh:
                        output = json.load(fh)
                    result = output["results"][0]
                except (OSError, json.JSONDecodeError, KeyError, IndexError) as exc:
                    raise RuntimeError(
                        f"failed to read psynet performance-test output for "
                        f"demo={self.demo_name!r} combo={combo!r} "
                        f"json_path={json_path!r}: {exc}"
                    ) from exc
            finally:
                Path(json_path).unlink(missing_ok=True)

            results[combo] = result

        return results

    @staticmethod
    def _result_for(data, *param_values):
        return data[tuple(param_values)]

    def track_median_response_time_ms(self, data, *param_values):
        value = self._result_for(data, *param_values)["median_response_time"]
        if value is None:
            raise RuntimeError("performance test recorded no median response time")
        return value * 1000.0

    track_median_response_time_ms.unit = "ms"
    track_median_response_time_ms.pretty_name = "Median request time"

    def track_export_time_s(self, data, *param_values):
        result = self._result_for(data, *param_values)
        duration = result.get("export_duration_s")
        if duration is None:
            raise RuntimeError(
                "export_duration_s not in result — was --no-export passed?"
            )
        return duration

    track_export_time_s.unit = "s"
    track_export_time_s.pretty_name = "Export time"


class Timeline(_BaseExperiment):
    demo_name = "timeline"
    # n_bots set to the throughput knee from the load sweep (benchmark_load_sweep
    # CI job). Longer duration than the other demos: Timeline's bots are slow,
    # so a short run yields too little completed-request data for stable median
    # request timing.
    params = [[12], [8.0]]

    # See `_BaseExperiment.setup_cache` for why each subclass must redefine
    # this method (ASV cache-key collision on inherited methods).
    def setup_cache(self):
        return super().setup_cache()


class Static(_BaseExperiment):
    demo_name = "static"
    # n_bots set to the throughput knee located by the load sweep on GitLab
    # runners (benchmark_load_sweep CI job).
    params = [[5], [2.0]]

    def setup_cache(self):
        return super().setup_cache()


class StaticBig(_BaseExperiment):
    demo_name = "static_big"
    demo_root = "tests/experiments"
    # n_bots set to the throughput knee located by the load sweep on GitLab
    # runners (benchmark_load_sweep CI job).
    params = [[5], [2.0]]

    def setup_cache(self):
        return super().setup_cache()


class AsyncProcesses(_BaseExperiment):
    demo_name = "async_processes"
    demo_root = "tests/experiments"
    params = [[5], [2.0]]

    def setup_cache(self):
        return super().setup_cache()

    def track_median_queue_delay_ms(self, data, *param_values):
        value = self._result_for(data, *param_values)["q_delay_median"]
        if value is None:
            raise RuntimeError("performance test recorded no async process queue delay")
        return value * 1000.0

    track_median_queue_delay_ms.unit = "ms"
    track_median_queue_delay_ms.pretty_name = "async_processes Median queue delay"
