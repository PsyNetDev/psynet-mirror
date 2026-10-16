import json
import multiprocessing
import threading
import time

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


def test_shard_fails_when_an_item_has_no_result(tmp_path, monkeypatch):
    items = [SuiteItem("lost", "isolated", estimate=1)]
    monkeypatch.setattr(ci_tests, "collect_items", lambda scope, durations: items)
    monkeypatch.setattr(ci_tests, "run_items", lambda *args: [])

    code = ci_tests.run_tests_command(
        "isolated", 1, 1, 1, 60, None, "3.13", None, tmp_path
    )

    assert code == 1


def test_slot_ports_are_offset_from_the_callers(monkeypatch):
    monkeypatch.setenv("base_port", "5010")

    assert ci_tests._caller_base_port() == 5010
    assert ci_tests._slot_ports(5010, "redis://localhost:6380", 1) == (5020, 6480)
    assert ci_tests._slot_ports(5000, "", 2) == (5020, 6579)


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
