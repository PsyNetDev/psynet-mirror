import subprocess
import sys

import pytest

pytest_plugins = ["pytest_dallinger", "pytest_psynet"]
# import psynet.pytest_psynet  # noqa


@pytest.fixture
def db_client_in_other_process():
    """Hold a connection to the local database from another process; yield its backend pid."""
    import dallinger.db

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
    try:
        yield int(process.stdout.readline())
    finally:
        process.communicate()
