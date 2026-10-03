"""Cooperative psycopg2 waits in gevent processes.

gevent monkey-patching cannot be undone, so the gevent scenarios run in a
subprocess.
"""

import json
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import psycopg2.extensions
from dallinger.db import db_url

from psynet.db import install_gevent_wait_callback
from psynet.experiment import _is_replacement_gunicorn_worker

_SCRIPT = textwrap.dedent(
    """
    import sys

    mode, dsn = sys.argv[1], sys.argv[2]
    if mode == "imported_before_patching":
        import dallinger.db  # noqa: F401

    from gevent import monkey

    monkey.patch_all()

    import io
    import json
    import time

    import gevent
    import psycopg2
    from psycopg2.extensions import get_wait_callback

    result = {}
    if mode != "stock":
        import dallinger.db

        from psynet.db import blocking_psycopg, install_gevent_wait_callback

        result["installed_on_import"] = get_wait_callback() is not None
        result["installed_again"] = install_gevent_wait_callback()
    if mode == "imported_before_patching":
        print(json.dumps(result))
        sys.exit()

    key = 815_100_001
    holder, waiter = psycopg2.connect(dsn), psycopg2.connect(dsn)

    def hold():
        holder.cursor().execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        gevent.sleep(0.3)
        holder.commit()

    def wait():
        gevent.sleep(0.1)
        cur = waiter.cursor()
        cur.execute("SET lock_timeout = '2s'")
        start = time.monotonic()
        try:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            result["waited"] = time.monotonic() - start
        except psycopg2.Error as err:
            result["wait_error"] = type(err).__name__
        waiter.rollback()

    gevent.joinall([gevent.spawn(hold), gevent.spawn(wait)], raise_error=True)

    if mode == "green":
        cur = holder.cursor()
        try:
            cur.copy_expert("COPY (SELECT 1) TO STDOUT", io.StringIO())
            result["copy_outside"] = "ok"
        except psycopg2.ProgrammingError:
            result["copy_outside"] = "error"
        holder.rollback()
        out = io.StringIO()
        with blocking_psycopg():
            cur.copy_expert("COPY (SELECT 1) TO STDOUT", out)
        result["copy_inside"] = out.getvalue().strip()

        def suspend(first_delay, second_delay):
            gevent.sleep(first_delay)
            with blocking_psycopg():
                gevent.sleep(second_delay)

        # Overlapping suspensions: the first exits while the second is active.
        greenlets = [gevent.spawn(suspend, 0, 0.05), gevent.spawn(suspend, 0.02, 0.1)]
        gevent.sleep(0.07)
        result["suspended_during_overlap"] = get_wait_callback() is None
        gevent.joinall(greenlets, raise_error=True)
        result["restored_after_overlap"] = get_wait_callback() is not None

        dallinger.db.engine.dispose()
        with blocking_psycopg():
            dallinger.db.engine.connect().close()
            result["suspended_across_new_connection"] = get_wait_callback() is None

    print(json.dumps(result))
    """
)


def _run(mode):
    completed = subprocess.run(
        [sys.executable, "-c", _SCRIPT, mode, db_url],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_lock_wait_freezes_a_gevent_process_without_the_callback():
    result = _run("stock")
    assert result == {"wait_error": "LockNotAvailable"}


def test_wait_callback_lets_the_lock_holder_finish():
    result = _run("green")
    assert result["installed_on_import"] is True
    assert result["installed_again"] is False
    assert result["waited"] < 1.5
    assert result["copy_outside"] == "error"
    assert result["copy_inside"] == "1"
    assert result["suspended_during_overlap"] is True
    assert result["restored_after_overlap"] is True
    assert result["suspended_across_new_connection"] is True


def test_install_refuses_when_dallinger_was_imported_before_patching():
    """Greenlets would share one session and deadlock on its connection."""
    assert _run("imported_before_patching") == {
        "installed_on_import": False,
        "installed_again": False,
    }


def test_install_is_a_no_op_without_gevent_patching():
    assert install_gevent_wait_callback() is False
    assert psycopg2.extensions.get_wait_callback() is None


def test_only_replacement_gunicorn_workers_count_as_restarts():
    cfg = SimpleNamespace(workers=2)
    assert not _is_replacement_gunicorn_worker(SimpleNamespace(age=1, cfg=cfg))
    assert not _is_replacement_gunicorn_worker(SimpleNamespace(age=2, cfg=cfg))
    assert _is_replacement_gunicorn_worker(SimpleNamespace(age=3, cfg=cfg))
