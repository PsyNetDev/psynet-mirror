"""The experiment server that ``psynet performance-test local`` starts and restarts.

A database reset (see :mod:`psynet.perf_reset`) needs the server stopped
while it copies the database, and started again afterwards. The server first
starts with ``psynet debug local --legacy``, which prepares a fresh database
and launches the experiment, so it can't simply run again. Instead, restarts
run the ``heroku local`` command that Dallinger ran to start the web, worker
and clock processes, rebuilt from the config of the running server, in the
server's working directory.

:class:`RestartableLocalServer` generates a Flask secret key and starts the
server with it in its environment. Dallinger's debug deployment keeps a
preset key, so restarts with the same environment keep dashboard logins,
such as those of the bots, valid. The key never appears in the output.
"""

import os
import secrets
import signal
import subprocess
import time

import click

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
        from psynet.command_line import (
            _start_local_server_and_wait_for_ready,
            local_server_env,
        )

        extra_env = {
            "PSYNET_PERFORMANCE_TEST": "1",
            "FLASK_SECRET_KEY": secrets.token_hex(16),
        }
        self._info = _start_local_server_and_wait_for_ready(
            ["debug", "local", "--legacy", "--no-browsers"],
            debug=debug,
            extra_env=extra_env,
        )
        self._log_path = self._info["tmp_log_path"]
        self._process = None
        self._n_workers = 0
        self._recipe = None
        if restartable:
            try:
                self._recipe = (*_heroku_local_command(), local_server_env(extra_env))
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
        cmdline, cwd, port, env = self._recipe
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
        """Stop the server if it is running.

        A stop that is interrupted, for example by Ctrl+C, is tried again at
        the next call.
        """
        from psynet.command_line import _stop_server, kill_psynet_worker_processes

        if self._info is not None:
            _stop_server(self._info)
            self._info = None
        if self._process is not None:
            try:
                _stop_process_group(self._process)
            finally:
                kill_psynet_worker_processes()
            self._process = None
            print(f"✓ Server stopped (log: {self._log_path})")


def _heroku_local_command():
    """Return the ``heroku local`` command of the running server, its working directory and port.

    The command matches the one Dallinger's ``HerokuLocalWrapper`` runs, with
    the dyno counts from the server's ``config.txt``.
    """
    from dallinger.heroku.tools import dyno_count

    from psynet.redis import redis_vars
    from psynet.utils import load_runtime_server_config

    cwd = redis_vars.get("server_working_directory", None)
    if not cwd:
        raise click.ClickException(
            "The experiment server didn't record its working directory, so it "
            "can't be restarted to reset the database."
        )
    config = load_runtime_server_config()
    dynos = f"web={dyno_count(config, 'web')},worker={dyno_count(config, 'worker')}"
    if config.get("clock_on"):
        dynos += ",clock"
    port = config.get("base_port")
    return ["heroku", "local", "-p", str(port), dynos], cwd, port


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
        except PermissionError:
            # macOS reports EPERM for a group that only has zombies left;
            # _group_alive tells whether the group has stopped.
            pass
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
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS reports EPERM for a group that only has zombies left, but
        # the group isn't stopped while its leader still runs.
        return process.returncode is None
    return True
