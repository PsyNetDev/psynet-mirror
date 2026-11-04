import subprocess
import sys
import time

import pytest

pytest_plugins = ["pytest_dallinger", "pytest_psynet"]
# import psynet.pytest_psynet  # noqa


@pytest.fixture
def db_client_in_other_process():
    """Hold a connection to the local database from another process; yield its backend pid."""
    import dallinger.db
    from sqlalchemy import text

    hold_connection = (
        "import sys, psycopg2; c = psycopg2.connect(sys.argv[1]); "
        "print(c.get_backend_pid(), flush=True); sys.stdin.read()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", hold_connection, dallinger.db.db_url],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    pid = None
    try:
        pid = int(process.stdout.readline())
        yield pid
    finally:
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        # Later tests must not see the backend while it shuts down.
        deadline = time.monotonic() + 2
        while pid is not None and time.monotonic() < deadline:
            # A new transaction each time, as pg_stat_activity is a snapshot.
            with dallinger.db.engine.connect() as con:
                still_there = con.execute(
                    text("SELECT 1 FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": pid},
                ).first()
            if not still_there:
                break
            time.sleep(0.05)
