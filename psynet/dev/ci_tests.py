"""Run PsyNet's CI test suite in balanced shards with parallel slots.

CI splits the suite (demo experiment directories plus ``tests/isolated``
files) across several GitLab jobs ("shards"). Each item runs in its own pytest
process because experiments cannot be fully unloaded within one session.

Two things make this faster than running items one after another:

- **Balanced shards.** Items are assigned with the longest-processing-time
  rule using the durations recorded in :data:`DURATIONS_PATH`, so no shard
  is stuck with several of the slowest tests. Items without a recorded
  duration get the median for their kind.
- **Slots.** A shard can run several items at once. Each slot is a separate
  local PsyNet environment: its own Postgres database, Redis server, web
  port and Dallinger develop directory. A Redis server (not just a database
  number) is needed because Redis pub/sub channels are shared across
  database numbers. Slot 0 uses the caller's environment, so ``--slots 1``
  behaves like a plain serial run (outside CI, its pytest sessions still
  isolate themselves; see :mod:`psynet.isolated_environment`).

Items that share an experiment directory are serialized by
:func:`psynet.testing.locks.experiment_directory_lock`.

The Playwright jobs reuse the same balancing: ``playwright-files`` prints the
spec files for one shard, because Playwright's own ``--shard`` splits by test
count, and a single spec of 40 sub-second layout tests then fills a shard.
Playwright durations are keyed ``<spec>::<mode>`` since the default and
legacy jobs select different tests from the same files.

Refresh the durations after the suite changes noticeably with
``psynet dev ci update-test-durations``, passing the ``ci_durations_*.json``
artifacts written by ``run-tests`` and the ``playwright-*-junit.xml`` reports.
"""

import heapq
import json
import os
import re
import shutil
import statistics
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import click

from psynet.isolated_environment import (
    DEFAULT_DATABASE_URL,
    READY_ENV_VAR,
    ensure_database,
    start_redis_server,
    stop_process,
)
from psynet.testing.locks import HELD_LOCK_ENV_VAR, experiment_directory_lock
from psynet.utils import get_psynet_root, list_experiment_dirs, list_isolated_tests

DURATIONS_PATH = Path("ci/test_durations.json")
PLAYWRIGHT_DIR = Path("tests/playwright")

_COMMON_PYTEST_ARGS = [
    "-Werror",
    "-W",
    "ignore:color, on_color and attrs are not supported when output stream is not a TTY:UserWarning:yaspin.core",
    "-q",
    "-o",
    "log_cli=False",
    "--chrome",
]
# The custom_network_filter deprecation is ignored until psynet-step migrates
# to custom_chain_filter (https://github.com/pmcharrison/STEP/pull/5).
_DEMO_PYTEST_ARGS = [
    "-W",
    "ignore:custom_network_filter is deprecated:DeprecationWarning",
]


@dataclass
class SuiteItem:
    """One pytest process: a demo directory or an isolated test file."""

    path: str
    kind: str
    estimate: float = 0.0

    @property
    def absolute_path(self):
        return str(get_psynet_root() / self.path)


@dataclass
class ItemResult:
    item: SuiteItem
    slot: int
    returncode: int
    duration: float
    output: str


def collect_items(scope, durations):
    """List the demo and isolated test items for ``scope`` with duration estimates."""
    root = get_psynet_root()
    items = []
    if scope == "full":
        items += [
            SuiteItem(os.path.relpath(path, root), "demo")
            for path in list_experiment_dirs(for_ci_tests=True)
        ]
    items += [
        SuiteItem(os.path.relpath(path, root), "isolated")
        for path in sorted(list_isolated_tests())
    ]
    for kind in {item.kind for item in items}:
        _apply_estimates([i for i in items if i.kind == kind], durations)
    return items


def _apply_estimates(items, durations, key=lambda item: item.path):
    """Set estimates from ``durations``, using the median for unknown items."""
    known = [durations[key(i)] for i in items if key(i) in durations]
    default = statistics.median(known) if known else 30.0
    for item in items:
        item.estimate = durations.get(key(item), default)


def assign_shard(items, node_total, node_index):
    """Return the items for shard ``node_index`` (1-based) of ``node_total``.

    Uses the longest-processing-time rule, so shards end up with similar total
    estimated durations. Ties are broken by path, keeping the assignment
    identical on every shard.
    """
    loads = [(0.0, shard) for shard in range(node_total)]
    assigned = {shard: [] for shard in range(node_total)}
    for item in sorted(items, key=lambda i: (-i.estimate, i.path)):
        load, shard = heapq.heappop(loads)
        assigned[shard].append(item)
        heapq.heappush(loads, (load + item.estimate, shard))
    return assigned[node_index - 1]


def _durations_path():
    return get_psynet_root() / DURATIONS_PATH


def load_durations():
    """Return the recorded durations in :data:`DURATIONS_PATH`, keyed by item."""
    path = _durations_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


class _Slot:
    """An isolated local environment (database, Redis, port) for one worker."""

    def __init__(self, index, workspace):
        self.index = index
        self.env = dict(os.environ)
        self._redis = None
        self._redis_log = None
        if index == 0:
            return

        database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        base_port, redis_port = _slot_ports(
            _caller_base_port(), os.environ.get("REDIS_URL", ""), index
        )
        self.env[READY_ENV_VAR] = "1"
        self.env["DATABASE_URL"] = ensure_database(
            database_url, suffix=f"_slot{index}", fresh=True
        )
        self.env["REDIS_URL"] = self._start_redis(redis_port, workspace)
        self.env["base_port"] = str(base_port)
        self.env["dallinger_develop_directory"] = (
            f"/tmp/dallinger_develop_{base_port}_slot{index}"
        )

    def _start_redis(self, port, workspace):
        if shutil.which("redis-server") is None:
            raise click.ClickException(
                "--slots > 1 needs redis-server on PATH to give each slot its own Redis."
            )
        self._redis_log = open(workspace / f"redis_slot{self.index}.log", "w")
        try:
            self._redis = start_redis_server(port, workspace, log_file=self._redis_log)
        except RuntimeError as e:
            self.close()
            raise click.ClickException(f"Redis for slot {self.index}: {e}") from e
        return f"redis://127.0.0.1:{port}"

    def close(self):
        if self._redis is not None:
            stop_process(self._redis)
            self._redis = None
        if self._redis_log is not None:
            self._redis_log.close()
            self._redis_log = None


def _caller_base_port():
    """Return the caller's ``base_port``, from the environment or Dallinger's config files."""
    if "base_port" in os.environ:
        return int(os.environ["base_port"])
    from dallinger.config import get_config

    config = get_config()
    if not config.ready:
        config.load()
    return config.get("base_port")


def _slot_ports(base_port, redis_url, index):
    """Return ``(base_port, redis_port)`` for slot ``index``, offset from the caller's."""
    redis_port = (urlsplit(redis_url).port or 6379) + 100 * index
    return base_port + 10 * index, redis_port


def _junit_args(item, junit_dir, python_version):
    if junit_dir is None:
        return []
    test_id = item.absolute_path.replace("/", "_").replace(".", "_")
    return [
        f"--junitxml={junit_dir}/{python_version}_{test_id}_junit.xml",
        "-o",
        f"junit_suite_name=py{python_version}",
    ]


def _run(cmd, env, cwd=None):
    completed = subprocess.run(
        cmd,
        env=env,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.returncode, completed.stdout


def _run_item(item, slot, timeout, junit_dir, python_version):
    pytest_args = [
        *_COMMON_PYTEST_ARGS,
        f"--timeout={timeout}",
        *_junit_args(item, junit_dir, python_version),
    ]
    if item.kind == "isolated":
        return _run(["pytest", item.absolute_path, *pytest_args], slot.env)

    directory = item.absolute_path
    with experiment_directory_lock(directory, export=False):
        env = {**slot.env, HELD_LOCK_ENV_VAR: os.path.realpath(directory)}
        code, output = _run(
            ["psynet", "scripts", "scaffold", "--skip-constraints"], env, cwd=directory
        )
        if code == 0:
            code, test_output = _run(
                [
                    "pytest",
                    f"{directory}/test.py",
                    *pytest_args,
                    *_DEMO_PYTEST_ARGS,
                ],
                env,
            )
            output += test_output
        prune_code, prune_output = _run(
            ["psynet", "scripts", "prune", "--include-modified"], env, cwd=directory
        )
        output += prune_output
        if prune_code != 0:
            output += f"\nFailed to restore authored-only layout for {directory}\n"
            code = code or prune_code
    return code, output


def run_items(items, n_slots, timeout, junit_dir, python_version, log_dir):
    """Run ``items`` longest-first on ``n_slots`` parallel slots."""
    log_dir.mkdir(parents=True, exist_ok=True)
    queue = sorted(items, key=lambda i: (-i.estimate, i.path))
    lock = threading.Lock()
    print_lock = threading.Lock()
    results = []

    def worker(slot):
        while True:
            with lock:
                if not queue:
                    return
                item = queue.pop(0)
            start = time.monotonic()
            try:
                code, output = _run_item(item, slot, timeout, junit_dir, python_version)
            except Exception:
                # A dead worker would drop its remaining items from the shard
                # without failing it, so record the crash as a failure instead.
                code, output = 1, traceback.format_exc()
            result = ItemResult(
                item, slot.index, code, time.monotonic() - start, output
            )
            with print_lock:
                results.append(result)
            log_name = item.path.replace("/", "__") + ".log"
            (log_dir / log_name).write_text(output)
            with print_lock:
                status = "PASSED" if code == 0 else "FAILED"
                print(
                    f"[slot {slot.index}] {status} {result.duration:6.1f}s "
                    f"(est {item.estimate:5.1f}s) {item.path}",
                    flush=True,
                )
                if code != 0:
                    print(f"----- output of {item.path} -----\n{output}", flush=True)

    slots = []
    threads = []
    try:
        for index in range(n_slots):
            slots.append(_Slot(index, log_dir))
        threads = [threading.Thread(target=worker, args=(slot,)) for slot in slots]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    except BaseException:
        # On Ctrl+C the terminal also interrupts the running pytest processes;
        # emptying the queue stops workers from starting new ones.
        with lock:
            queue.clear()
        for thread in threads:
            thread.join()
        raise
    finally:
        for slot in slots:
            slot.close()
    return results


def run_tests_command(
    scope,
    node_total,
    node_index,
    slots,
    timeout,
    junit_dir,
    python_version,
    durations_output,
    log_dir,
):
    """Run one CI shard and return the process exit code."""
    durations = load_durations()
    items = assign_shard(collect_items(scope, durations), node_total, node_index)
    estimate = sum(i.estimate for i in items)
    print(
        f"Shard {node_index}/{node_total}: {len(items)} items, "
        f"estimated {estimate / 60:.1f} min of test time on {slots} slot(s)",
        flush=True,
    )
    start = time.monotonic()
    results = run_items(
        items, slots, timeout, junit_dir, python_version, Path(log_dir).absolute()
    )
    wall = time.monotonic() - start
    failed = [r for r in results if r.returncode != 0]
    busy = sum(r.duration for r in results)
    print(
        f"\nShard {node_index}/{node_total} finished in {wall / 60:.1f} min: "
        f"{len(results) - len(failed)} passed, {len(failed)} failed; "
        f"{busy / 60:.1f} min of test time on {slots} slot(s) "
        f"(slot utilization {busy / (wall * slots) if wall else 0:.0%})"
    )
    for result in failed:
        print(f"  FAILED {result.item.path}")
    missing = {i.path for i in items} - {r.item.path for r in results}
    for path in sorted(missing):
        print(f"  NOT RUN {path}")

    if durations_output:
        Path(durations_output).parent.mkdir(parents=True, exist_ok=True)
        Path(durations_output).write_text(
            json.dumps(
                {
                    "slots": slots,
                    "wall_seconds": wall,
                    "durations": {r.item.path: round(r.duration, 1) for r in results},
                },
                indent=1,
                sort_keys=True,
            )
        )
    return 1 if failed or missing else 0


def _playwright_key(spec, mode):
    return f"{spec}::{mode}"


def playwright_files_command(mode, node_total, node_index):
    """Print the Playwright spec files for one shard of the ``mode`` CI job."""
    root = get_psynet_root()
    items = [
        SuiteItem(path.relative_to(root).as_posix(), "playwright")
        for path in sorted((root / PLAYWRIGHT_DIR).rglob("*.spec.js"))
    ]
    _apply_estimates(
        items, load_durations(), key=lambda i: _playwright_key(i.path, mode)
    )
    click.echo(" ".join(i.path for i in assign_shard(items, node_total, node_index)))


def _playwright_junit_durations(path):
    """Sum test times per spec file in a ``playwright-<mode>-<shard>-junit.xml`` report."""
    import xml.etree.ElementTree as ET

    match = re.search(r"(default|legacy)", Path(path).name)
    if match is None:
        raise click.ClickException(f"Cannot tell the Playwright mode of {path}.")
    mode = match.group(1)
    durations = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        key = _playwright_key(f"{PLAYWRIGHT_DIR}/{case.get('classname')}", mode)
        durations[key] = durations.get(key, 0.0) + float(case.get("time") or 0)
    return durations


def update_test_durations_command(paths):
    """Merge duration artifacts into :data:`DURATIONS_PATH`.

    Accepts the JSON files written by ``run-tests`` and the
    ``playwright-<mode>-<shard>-junit.xml`` reports of the Playwright jobs. Entries
    for paths that no longer exist are dropped.
    """
    samples = {}
    for path in paths:
        if str(path).endswith(".xml"):
            durations = _playwright_junit_durations(path)
        else:
            durations = json.loads(Path(path).read_text())["durations"]
        for name, duration in durations.items():
            samples.setdefault(name, []).append(duration)
    root = get_psynet_root()
    merged = {
        name: duration
        for name, duration in load_durations().items()
        if (root / name.split("::")[0]).exists()
    }
    merged.update({name: round(statistics.median(v), 1) for name, v in samples.items()})
    _durations_path().write_text(json.dumps(merged, indent=1, sort_keys=True) + "\n")
    click.echo(
        f"Updated {len(samples)} of {len(merged)} durations in {DURATIONS_PATH}."
    )
