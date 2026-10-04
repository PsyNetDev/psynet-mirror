import json
import multiprocessing
import threading
import time

from click.testing import CliRunner

from psynet.command_line import psynet
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
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci").mkdir()
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
    durations = json.loads((tmp_path / "ci/test_durations.json").read_text())
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
