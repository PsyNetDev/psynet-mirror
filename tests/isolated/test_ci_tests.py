import json
import multiprocessing
import os
import threading
import time

import click
import pytest
from click.testing import CliRunner

from psynet.command_line import psynet
from psynet.dev import ci_tests
from psynet.dev.ci_tests import SuiteItem, assign_shard
from psynet.testing.locks import experiment_directory_lock
from psynet.utils import get_psynet_root


def test_assign_shard_balances_and_covers_every_item():
    items = [
        SuiteItem(f"t{i}", "isolated", estimate=d)
        for i, d in enumerate([9, 7, 6, 5, 4, 3, 2, 2])
    ]

    shards = [assign_shard(items, 3, index) for index in (1, 2, 3)]

    assert sorted(i.path for shard in shards for i in shard) == sorted(
        i.path for i in items
    )
    assert sorted(sum(i.estimate for i in shard) for shard in shards) == [12, 13, 13]


def test_playwright_durations_feed_balanced_spec_shards(tmp_path, monkeypatch):
    durations_path = tmp_path / "test_durations.json"
    monkeypatch.setattr(ci_tests, "DURATIONS_PATH", durations_path)
    report = tmp_path / "playwright-legacy-1-junit.xml"
    report.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="timeline_hold.spec.js" time="900"/>'
        '<testcase classname="timeline_hold.spec.js" time="100"/>'
        '<testcase classname="early_exit.spec.js" time="1"/>'
        '<testcase classname="theme_layout.spec.js" time="1"/>'
        "</testsuite></testsuites>"
    )
    runner = CliRunner()

    result = runner.invoke(psynet, ["dev", "ci", "update-test-durations", str(report)])
    assert result.exit_code == 0, result.output
    durations = json.loads(durations_path.read_text())
    assert durations["tests/playwright/timeline_hold.spec.js::legacy"] == 1000.0

    shards = [
        runner.invoke(
            psynet,
            ["dev", "ci", "playwright-files", "--mode", "legacy", "--node-total", "2"]
            + ["--node-index", str(index)],
        ).output.split()
        for index in (1, 2)
    ]
    assert shards[0] == ["tests/playwright/timeline_hold.spec.js"]
    specs = (get_psynet_root() / "tests/playwright").rglob("*.spec.js")
    assert len(shards[1]) == len(list(specs)) - 1


def test_crashed_item_counts_as_failure(tmp_path, monkeypatch):
    def run_item(item, *args):
        if item.path == "crashes":
            raise OSError("scaffold vanished")
        return 0, "ok"

    monkeypatch.setattr(ci_tests, "_run_item", run_item)
    items = [SuiteItem("crashes", "demo"), SuiteItem("passes", "isolated")]

    results = ci_tests.run_items(items, 1, 60, None, "3.13", tmp_path)

    assert {r.item.path: r.returncode for r in results} == {"crashes": 1, "passes": 0}
    assert "scaffold vanished" in results[0].output


def test_sigterm_stops_running_tests_and_closes_the_slots(tmp_path):
    import signal
    import subprocess
    import sys

    import psutil

    pid_file, closed_file = tmp_path / "test.pid", tmp_path / "closed"
    test = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    script = (
        "import os, pathlib, sys\n"
        "from psynet.dev import ci_tests\n"
        "class Slot:\n"
        "    def __init__(self, index):\n"
        "        self.index, self.env = index, dict(os.environ)\n"
        "    def close(self):\n"
        f"        open({str(closed_file)!r}, 'w').close()\n"
        "ci_tests._Slot = Slot\n"
        "ci_tests._run_item = lambda item, slot, *args: ci_tests._run("
        f"[sys.executable, '-c', {test!r}], slot.env)\n"
        "items = [ci_tests.SuiteItem('sleeps', 'isolated', estimate=1)]\n"
        f"ci_tests.run_items(items, 1, 60, None, '3.13', pathlib.Path({str(tmp_path)!r}))\n"
    )
    runner = subprocess.Popen([sys.executable, "-c", script])
    pids = [runner.pid]
    try:
        deadline = time.monotonic() + 60
        while not pid_file.exists() or not pid_file.read_text():
            assert runner.poll() is None and time.monotonic() < deadline
            time.sleep(0.1)
        pids.append(int(pid_file.read_text()))

        runner.send_signal(signal.SIGTERM)
        assert runner.wait(timeout=30) == 128 + signal.SIGTERM
        assert not psutil.pid_exists(pids[1])
        assert closed_file.exists()
    finally:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_shard_fails_when_an_item_has_no_result(tmp_path, monkeypatch):
    items = [SuiteItem("lost", "isolated", estimate=1)]
    monkeypatch.setattr(ci_tests, "collect_items", lambda scope, durations: items)
    monkeypatch.setattr(ci_tests, "run_items", lambda *args: [])

    code = ci_tests.run_tests_command(
        "isolated", 1, 1, 1, 60, None, "3.13", None, tmp_path
    )

    assert code == 1


def test_slots_get_their_own_services(monkeypatch):
    monkeypatch.setenv("base_port", "5010")
    first, second = ci_tests._Slot(0), ci_tests._Slot(1)
    try:
        assert first.env == dict(os.environ)
        assert int(second.env["base_port"]) >= 5110
        assert second.env["DATABASE_URL"] != os.environ.get("DATABASE_URL")
    finally:
        second.close()
        first.close()


def test_slot_0_is_isolated_outside_ci(monkeypatch):
    monkeypatch.setattr(ci_tests, "should_isolate", lambda: True)
    slot = ci_tests._Slot(0)
    try:
        assert slot.env["DATABASE_URL"] != os.environ.get("DATABASE_URL")
    finally:
        slot.close()


def test_extra_slots_need_their_own_redis_server(monkeypatch):
    monkeypatch.setattr(ci_tests.shutil, "which", lambda name: None)

    with pytest.raises(click.ClickException, match="needs redis-server"):
        ci_tests._Slot(1)


def _hold_lock(directory, held, release):
    with experiment_directory_lock(directory):
        held.set()
        release.wait(10)


def test_directory_lock_excludes_other_processes(tmp_path):
    held, release = multiprocessing.Event(), multiprocessing.Event()
    other = multiprocessing.Process(target=_hold_lock, args=(tmp_path, held, release))
    other.start()
    assert held.wait(10)

    threading.Timer(0.5, release.set).start()
    start = time.monotonic()
    with experiment_directory_lock(tmp_path):
        assert time.monotonic() - start >= 0.4
    other.join(10)
