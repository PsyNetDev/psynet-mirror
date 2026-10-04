import multiprocessing
import threading
import time

from psynet.dev.ci_tests import SuiteItem, assign_shard
from psynet.testing.locks import experiment_directory_lock


def test_assign_shard_balances_and_covers_every_item():
    items = [SuiteItem(f"t{i}", "isolated", estimate=d) for i, d in enumerate([9, 7, 6, 5, 4, 3, 2, 2])]

    shards = [assign_shard(items, 3, index) for index in (1, 2, 3)]

    assert sorted(i.path for shard in shards for i in shard) == sorted(i.path for i in items)
    assert sorted(sum(i.estimate for i in shard) for shard in shards) == [12, 13, 13]


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
