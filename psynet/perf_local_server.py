"""The experiment server that ``psynet performance-test local`` starts and restarts.

A database reset (see :mod:`psynet.perf_reset`) needs the server stopped
while it copies the database, and started again afterwards. The server first
starts with ``psynet debug local --legacy``, which prepares a fresh database
and launches the experiment, so it can't simply run again. Instead, right
after that first start, :class:`RestartableLocalServer` records the ``heroku
local`` command that it ran, which starts the web, worker and clock
processes, with its working directory and environment, and later restarts
run that command. The environment includes the Flask secret key, so
dashboard logins stay valid across restarts.

``heroku local`` is a shell script that runs a Node program. On macOS the
environment of the protected ``bash`` can't be read, so the recipe is that
of the Node process. A change to the Heroku CLI's process tree would break
the lookup, which then fails with a clear error rather than guessing.
"""

import os
import signal
import subprocess
import time
from urllib.parse import urlsplit

import click
import psutil

from psynet.utils import get_experiment_url

_SERVER_READY_TIMEOUT_S = 120
_PORT_FREE_TIMEOUT_S = 30


class RestartableLocalServer:
    """The server of ``performance-test local``, which :meth:`stop` and :meth:`start` restart.

    Parameters
    ----------
    debug : bool
        Echo the server output.
    restartable : bool
        Record how to restart the server; without it, only :meth:`close`
        may be called.
    """

    def __init__(self, debug=False, restartable=False):
        from psynet.command_line import _start_local_server_and_wait_for_ready

        self._debug = debug
        self._info = _start_local_server_and_wait_for_ready(
            ["debug", "local", "--legacy", "--no-browsers"],
            debug=debug,
            extra_env={"PSYNET_PERFORMANCE_TEST": "1"},
        )
        self._log_path = self._info["tmp_log_path"]
        self._process = None
        self._n_workers = 0
        self._recipe = None
        if restartable:
            try:
                self._recipe = _find_heroku_local(self._info["process"].pid)
            except BaseException:
                self.close()
                raise

    def stop(self):
        """Stop the server's processes."""
        from dallinger.db import redis_conn
        from rq import Worker

        self._n_workers = Worker.count(connection=redis_conn)
        self.close()

    def start(self):
        """Start the server's processes again and wait until they serve requests."""
        cmdline, cwd, env, port = self._recipe
        _wait_for_free_port(port)
        print("▶ Restarting experiment server...")
        with open(self._log_path, "a", encoding="utf-8") as log:
            self._process = subprocess.Popen(
                cmdline,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _wait_until_server_ready(self._process, self._n_workers, self._log_path)

    def close(self):
        """Stop the server if it is running."""
        from psynet.command_line import _stop_server, kill_psynet_worker_processes

        if self._info is not None:
            info, self._info = self._info, None
            _stop_server(info)
        if self._process is not None:
            process, self._process = self._process, None
            try:
                _stop_process_group(process)
            finally:
                kill_psynet_worker_processes()
            print(f"✓ Server stopped (log: {self._log_path})")


def _find_heroku_local(pid):
    """Return the command line, working directory, environment and port of ``heroku local``.

    ``pid`` is the ``psynet debug local --legacy`` process that started it.
    """
    port = urlsplit(get_experiment_url()).port
    for process in psutil.Process(pid).children(recursive=True):
        try:
            cmdline = process.cmdline()
            if not _is_heroku_local(cmdline, port):
                continue
            env = process.environ()
            cwd = process.cwd()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "FLASK_SECRET_KEY" in env:
            return cmdline, cwd, env, port
    raise click.ClickException(
        "Could not find the heroku local process of the experiment server, so "
        "it can't be restarted to reset the database."
    )


def _is_heroku_local(cmdline, port):
    """Return whether ``cmdline`` runs ``heroku local -p <port>``."""
    try:
        i = cmdline.index("local")
    except ValueError:
        return False
    return any("heroku" in part for part in cmdline[:i]) and cmdline[i + 1 : i + 3] == [
        "-p",
        str(port),
    ]


def _wait_for_free_port(port):
    from psynet.isolated_environment import port_is_free

    deadline = time.monotonic() + _PORT_FREE_TIMEOUT_S
    while not port_is_free(port):
        if time.monotonic() >= deadline:
            raise click.ClickException(
                f"Port {port} is still in use {_PORT_FREE_TIMEOUT_S} s after the "
                "experiment server stopped, so it can't be restarted."
            )
        time.sleep(0.5)


def _wait_until_server_ready(process, n_workers, log_path):
    """Wait until the server answers /health and ``n_workers`` RQ workers have started."""
    import requests
    from dallinger.db import redis_conn
    from rq import Worker

    url = get_experiment_url() + "/health"
    deadline = time.monotonic() + _SERVER_READY_TIMEOUT_S
    while True:
        if process.poll() is not None:
            raise click.ClickException(
                f"The restarted experiment server exited with code "
                f"{process.returncode}; see {log_path}."
            )
        try:
            healthy = requests.get(url, timeout=10).ok
        except requests.RequestException:
            healthy = False
        if healthy and Worker.count(connection=redis_conn) >= n_workers:
            return
        if time.monotonic() >= deadline:
            raise click.ClickException(
                f"The restarted experiment server was not ready within "
                f"{_SERVER_READY_TIMEOUT_S} s; see {log_path}."
            )
        time.sleep(0.5)


def _stop_process_group(process):
    """Interrupt ``process`` and its group, escalating until the whole group exits."""
    for sig, timeout_s in (
        (signal.SIGINT, 15),
        (signal.SIGTERM, 5),
        (signal.SIGKILL, 5),
    ):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + timeout_s
        while _group_alive(process) and time.monotonic() < deadline:
            time.sleep(0.2)
        if not _group_alive(process):
            break
    else:
        raise click.ClickException(
            f"The experiment server (process group {process.pid}) did not stop, "
            "even after SIGKILL."
        )
    process.wait()


def _group_alive(process):
    """Return whether any process of ``process``'s group still runs."""
    process.poll()
    try:
        os.killpg(process.pid, 0)
    except (ProcessLookupError, PermissionError):
        # macOS reports EPERM for a group that only has zombies left.
        return False
    return True
