"""Run the tests of ``psynet performance-test ssh`` in an SSH app, and reset and pre-fill its database.

This computer drives the suite: each test is its own
``performance-test local --existing`` in the app's web container, whose
JSON result is read back. A reset has to stop that container, which would
stop a suite running inside it with it. With ``--reset-database``, between
tests :class:`DatabaseReset` stops the app's server processes with
:class:`RemoteApp`, restores the snapshot, and starts the processes again.
:class:`RemotePerformanceTester` is the tester that
:class:`psynet.perf_test.PerformanceSuite` sees, so the capacity search and
summaries are those of a local run.

How an app is laid out on the server (see Dallinger's ``docker_ssh``): its
files and ``docker-compose.yml`` are in ``~/dallinger/<app>/``; the stack has
``web``, ``worker_N``, optionally ``clock``, its own ``redis`` and a
``pgbouncer``, the front door's ``frontdoor``, ``controller`` and, with
Cloudflare ingress, ``cloudflared``; the database is named after the app and lives either in the
app's own ``<app>_postgresql`` container (Cloudflare ingress) or in the
server's shared ``dallinger-postgresql-1`` (classic ingress), which other
apps use too.

Design constraints:

- Performance tests only run on apps that ``performance-test ssh`` deployed
  for them, whose database is disposable. It deploys them with the config
  variable ``performance_test_app`` set, and the app's own config, read in
  its web container, is what says whether an app is one; that of this
  computer never counts. ``prepare-reset`` checks it again before every reset.
- SQL runs through ``docker exec <postgres container> psql`` as the
  container's superuser (:class:`_PsqlCursor`), never through an SSH
  tunnel, so the database is never reached as if it were local.
- Only the app's own database and the copies taken during the run are
  ever dropped. The database name comes from the web container's
  ``DATABASE_URL`` and must be the app name; the PostgreSQL container is
  the one Dallinger's export finds for the app.
- Before each reset the web container checks that the database has only bot
  participants and that the app doesn't recruit real ones (see
  ``psynet performance-test prepare-reset``); live mode always refuses.
- A reset stops every running or restarting service of the app's compose file except
  PostgreSQL, Redis and the front door's services (``_KEPT_SERVICES``),
  so that services added to the compose file that use the database can't
  hold it, and starts again only those it stopped. That includes
  pgbouncer: it keeps server connections to the database for 60 s after
  its clients go, and could open new ones while the database is copied.
  Starting it again also gives it a fresh pool.
- A worker that hangs in its start-up after a reset is left to Dallinger's
  ``worker_startup_timeout``, which exits it so that Docker restarts it;
  :meth:`RemoteApp.start` waits long enough for that.
- Secrets in the containers' environments never leave the server: commands
  print only what they need, such as the database name.
"""

import csv
import datetime
import hashlib
import io
import json
import logging
import os
import re
import shlex
import time
import uuid
from contextlib import contextmanager

from rich.text import Text

from psynet.perf_test import PerformanceTester, PerformanceTestResult
from psynet.perf_test.report import format_text, warning

logger = logging.getLogger(__name__)

_STATUS_MARKER = "__psynet_exit_status="
_SHARED_POSTGRES = "dallinger-postgresql-1"
_KEPT_SERVICES = frozenset(
    {"postgresql", "redis", "frontdoor", "controller", "cloudflared"}
)
# Covers Dallinger's 120 s worker_startup_timeout, Docker restarting the
# worker that it exits, and the new worker registering with RQ.
_SERVER_READY_TIMEOUT_S = 180
_WORKER_SERVICE = re.compile(r"worker_\d+")
_SERVICE_AND_HOSTNAME = (
    '{{index .Config.Labels "com.docker.compose.service"}} {{.Config.Hostname}}'
)
_REGISTERED_HOSTNAMES = (
    'for w in $(redis-cli SMEMBERS rq:workers); do redis-cli HGET "$w" hostname; done'
)
_SQLSTATE = re.compile(r"ERROR:\s+([0-9A-Z]{5}):")
_HEALTH_PROBE = (
    "import urllib.request; "
    "urllib.request.urlopen('http://localhost:5000/health', timeout=10)"
)
# Async jobs left from pre-filling would never run after a reset,
# because the reset deletes their RQ jobs.
_ASYNC_DRAIN_TIMEOUT_S = 3600
_IN_USE_ATTEMPTS = 10
_OBJECT_IN_USE = "55006"
_DUPLICATE_DATABASE = "42P04"
_MAX_NAME_LENGTH = 63
_SYSTEM_DATABASES = frozenset({"postgres", "template0", "template1", "dallinger"})
_SETTINGS_FILES = ("config.txt", "requirements.txt", "constraints.txt")


def experiment_code_key():
    """Return a short hash of the experiment's files and the PsyNet and Dallinger versions.

    ``performance-test ssh`` updates its app when this changes. The files are
    those that a deployment would copy, without the ones Git ignores, such
    as generated boilerplate, plus the ``_SETTINGS_FILES`` that exist.

    Raises
    ------
    ValueError
        If the experiment has no ``deploy.toml``.
    """
    import dallinger.version

    import psynet
    from psynet.deployment_info import authored_deployment_files

    files = authored_deployment_files()
    if files is None:
        raise ValueError("The experiment has no deploy.toml.")
    listed = {destination for destination, _ in files}
    files += [(name, name) for name in _SETTINGS_FILES if name not in listed]
    digest = hashlib.sha256(
        f"{psynet.__version__}\0{dallinger.version.__version__}".encode()
    )
    for destination, source in sorted(files):
        if not os.path.isfile(source):
            continue
        digest.update(f"\0{destination}\0".encode())
        with open(source, "rb") as f:
            while chunk := f.read(1 << 20):
                digest.update(chunk)
    return digest.hexdigest()[:12]


def run_with_status(executor, cmd):
    """Run shell command ``cmd`` on the server; return its exit status and output.

    The output is the command's stdout, followed by its stderr only if it
    fails, so that warnings on stderr, such as Docker Compose's, can't
    corrupt output that is parsed, and errors still say what went wrong.
    If the status never arrives, as when the SSH channel drops, the status
    is 255, like ``ssh``'s own.
    """
    script = (
        f'err=$(mktemp) && {{ {cmd} ; }} 2>"$err"; status=$?; '
        '[ "$status" -eq 0 ] || cat "$err"; rm -f "$err"; '
        f"echo {_STATUS_MARKER}$status"
    )
    output = executor.run(script, raise_=False) or ""
    if _STATUS_MARKER not in output:
        return 255, output
    output, _, status = output.rpartition(_STATUS_MARKER)
    return int(status.strip() or 1), output


class RemoteApp:
    """An app on an SSH server, as ``psynet performance-test ssh`` deployed it.

    Parameters
    ----------
    executor : dallinger.command_line.docker_ssh.Executor
        Runs commands on the server.
    app : str
        The app name.
    server : str
        The configured server name, for messages.
    force : bool
        Passed to the safety check (see :meth:`prepare`).
    bot_log_file : file, optional
        Bot output from the server is appended to it.
    """

    def __init__(self, executor, app, server, *, force=False, bot_log_file=None):
        self.executor = executor
        self.app = app
        self.server = server
        self.force = force
        self.bot_log_file = bot_log_file
        self._compose = (
            f"docker compose -f ~/dallinger/{shlex.quote(app)}/docker-compose.yml"
        )
        self._n_workers = 0
        # Services that stop() stopped, until start() starts them again.
        self._stopped = []

    def run(self, cmd):
        """Run ``cmd`` on the server and return its output.

        Raises
        ------
        RuntimeError
            If it fails.
        """
        status, output = run_with_status(self.executor, cmd)
        if status:
            raise RuntimeError(
                f"This command failed on {self.server} with exit status {status}: "
                f"{cmd}\n{output.strip()}"
            )
        return output

    def compose(self, *args):
        """Run ``docker compose`` with the app's compose file and return its output."""
        return self.run(" ".join([self._compose, *map(shlex.quote, args)]))

    def run_psynet(self, args, *, bot_log=False):
        """Run ``psynet <args> --json-output PATH`` in the web container and return that JSON.

        The output is echoed as it arrives. With ``bot_log``, the command
        also gets ``--bot-log``, whose contents are appended to
        :attr:`bot_log_file`.

        Raises
        ------
        click.ClickException
            If the command fails.
        RuntimeError
            If its JSON can't be read back.
        """
        from psynet.command_line import (
            _CONTAINER_WEB_PORT,
            build_remote_experiment_command,
            run_remote_experiment_command,
        )

        run_id = uuid.uuid4().hex
        json_path = f"/tmp/psynet_perf_{run_id}.json"
        log_path = f"/tmp/psynet_bots_{run_id}.log"
        cmd = (
            f"env PSYNET_EXPERIMENT_URL=http://localhost:{_CONTAINER_WEB_PORT} "
            f"psynet {args} --json-output {json_path}"
        )
        if bot_log:
            cmd += f" --bot-log {log_path}"
        try:
            run_remote_experiment_command(self.executor, self.app, cmd)
        finally:
            if bot_log:
                self._append_bot_log(log_path)
        read = shlex.quote(f"cat {json_path} && rm -f {json_path}")
        try:
            output = self.run(
                build_remote_experiment_command(self.app, f"sh -c {read}")
            )
            return json.loads(output)
        except (RuntimeError, ValueError) as e:
            raise RuntimeError(
                f"Could not read the results of 'psynet {args}' from {json_path} "
                f"in {self.app}'s web container: {e}"
            ) from e

    def prepare(self, *, prefill_participants=None, async_timeout_s=None):
        """Check that the app's database may be reset, optionally pre-fill it, and return how many async jobs are waiting.

        This runs ``psynet performance-test prepare-reset`` in the web
        container, which refuses an app that ``performance-test ssh`` didn't
        deploy or that runs in live mode and, unless
        :attr:`force`, one that has non-bot participants or a recruiter that
        may bring real ones. Then it adds ``prefill_participants`` bots'
        data, and waits up to ``async_timeout_s`` for async jobs to
        finish.

        Returns
        -------
        int
            The number of async jobs still waiting.
        """
        args = "performance-test prepare-reset"
        if self.force:
            args += " --force"
        if prefill_participants:
            args += f" --prefill-participants {int(prefill_participants)}"
        if async_timeout_s is not None:
            args += f" --wait-for-async-jobs {int(async_timeout_s)}"
        return self.run_psynet(args, bot_log=bool(prefill_participants))["waiting"]

    def database_name(self):
        """Return the name of the database in the web container's ``DATABASE_URL``."""
        probe = (
            "import os, urllib.parse; "
            "print(urllib.parse.urlsplit(os.environ['DATABASE_URL']).path.lstrip('/'))"
        )
        return self.compose("exec", "-T", "web", "python", "-c", probe).strip()

    def stop(self, check=True):
        """Check that the database may be reset, then stop the app's running or restarting services that may use the database.

        Those are all except PostgreSQL, Redis and the front door's
        services; :meth:`start` starts them again. Without ``check``, it
        skips the check, as when restoring a database that it already passed.

        Raises
        ------
        RuntimeError
            If none of them runs: without services, ``docker compose stop``
            would stop every service, PostgreSQL and Redis included.
        """
        if check:
            self.prepare()
        self._n_workers = int(self._redis("SCARD", "rq:workers") or 0)
        services = self._server_services()
        if not services:
            raise RuntimeError(
                f"None of {self.app}'s server processes, such as web, is running "
                f"on {self.server}, so its database can't be reset; see its logs "
                "in Dozzle."
            )
        print(f"▶ Stopping {self.app}'s server processes...")
        self._stopped = list(dict.fromkeys(self._stopped + services))
        self.compose("stop", *services)

    def start(self):
        """Start the services that :meth:`stop` stopped and wait until the server answers.

        It waits for ``/health`` in the web container and for as many RQ
        workers as there were before :meth:`stop`.

        Raises
        ------
        RuntimeError
            If the server isn't ready within ``_SERVER_READY_TIMEOUT_S``; the
            message names the worker containers that didn't register and
            how to restart them.
        """
        print(f"▶ Starting {self.app}'s server processes...")
        services = self._stopped
        if services:
            self.compose("start", *services)
        # Once started, waiting for them again after a failed reset wouldn't help.
        self._stopped = []
        workers = [s for s in services if _WORKER_SERVICE.fullmatch(s)]
        started = time.monotonic()
        next_progress_s = 20
        health = " ".join(
            [self._compose, "exec -T web python -c", shlex.quote(_HEALTH_PROBE)]
        )
        while True:
            healthy = run_with_status(self.executor, health)[0] == 0
            registered = int(self._redis("SCARD", "rq:workers") or 0)
            if healthy and registered >= self._n_workers:
                return
            waited = time.monotonic() - started
            if waited >= _SERVER_READY_TIMEOUT_S:
                raise RuntimeError(
                    self._not_ready_message(healthy, registered, workers)
                )
            if waited >= next_progress_s:
                waiting_for = (
                    f"worker processes to register ({registered} of {self._n_workers}; "
                    if registered < self._n_workers
                    else "the web server to answer ("
                )
                print(
                    f"  Waiting for {waiting_for}up to {_SERVER_READY_TIMEOUT_S} s)..."
                )
                next_progress_s = waited + 45
            time.sleep(2)

    def _not_ready_message(self, healthy, registered, workers):
        """Say why the server wasn't ready, naming worker containers that didn't register."""
        problems = [] if healthy else ["its web server didn't answer"]
        missing = []
        if registered < self._n_workers:
            missing = self._unregistered_workers(workers) or []
            problem = (
                f"{registered} of {self._n_workers} worker processes registered with RQ"
            )
            if missing:
                problem += f"; {', '.join(missing)} didn't"
            problems.append(problem)
        message = (
            f"{self.app} was not ready {_SERVER_READY_TIMEOUT_S} s after its "
            f"server processes started: {'; '.join(problems)}."
        )
        if missing:
            return (
                f"{message} Restart {'it' if len(missing) == 1 else 'them'} on "
                f"{self.server} with 'cd ~/dallinger/{self.app} && docker compose "
                f"restart {' '.join(missing)}', then run the test again."
            )
        return f"{message} See its logs in Dozzle."

    def _unregistered_workers(self, workers):
        """Return those of the ``workers`` services whose container has no RQ worker registration.

        RQ records each worker's hostname, which is its container's. If that
        can't be checked, it logs why and returns ``None``.
        """
        if not workers:
            return []
        try:
            containers = self.compose("ps", "-a", "-q", *workers).split()
            hostnames = dict(
                line.split()
                for line in self.run(
                    f"docker inspect --format {shlex.quote(_SERVICE_AND_HOSTNAME)} "
                    + " ".join(map(shlex.quote, containers))
                ).splitlines()
                if line.strip()
            )
            registered = set(
                self.compose(
                    "exec", "-T", "redis", "sh", "-c", _REGISTERED_HOSTNAMES
                ).split()
            )
        except (RuntimeError, ValueError) as e:
            logger.warning(
                f"Could not check which of {self.app}'s worker containers "
                f"registered with RQ: {e}"
            )
            return None
        return [s for s in workers if hostnames.get(s) not in registered]

    def start_stopped_services(self):
        """Start the services that :meth:`stop` stopped, if they haven't started again, as after a failed reset.

        If that fails or is interrupted, it prints the command that starts
        them by hand, then re-raises, so that the command fails.
        """
        if not self._stopped:
            return
        command = (
            f"cd ~/dallinger/{shlex.quote(self.app)} && docker compose start "
            + " ".join(map(shlex.quote, self._stopped))
        )
        try:
            self.start()
        except BaseException as e:
            reason = (str(e) or type(e).__name__).rstrip(".")
            stopped = Text(
                f"✗ {self.app} may be stopped: its server processes could not be "
                f"started again ({reason}). Start them on {self.server} with:",
                style="bright_red",
            )
            print("\n".join(format_text(stopped)))
            # Printed as is, so that the command can be copied whole.
            print(f"    {command}")
            print(
                "\n".join(
                    format_text(
                        "If the app still doesn't work, for example because the "
                        "reset had dropped its database, redeploy it."
                    )
                )
            )
            raise

    def clear_job_queues(self):
        """Delete the RQ queues, jobs and worker registrations from the app's Redis."""
        script = "redis-cli --scan --pattern 'rq:*' | xargs -r redis-cli DEL >/dev/null"
        self.compose("exec", "-T", "redis", "sh", "-c", script)

    def _redis(self, *command):
        return self.compose("exec", "-T", "redis", "redis-cli", *command).strip()

    def _server_services(self):
        """Return the running or restarting services that may use the database, such as web, workers, clock and pgbouncer."""
        running = self.compose(
            "ps", "--services", "--status", "running", "--status", "restarting"
        ).split()
        return [s for s in dict.fromkeys(running) if s not in _KEPT_SERVICES]

    def _append_bot_log(self, remote_path):
        from psynet.command_line import build_remote_experiment_command

        move = shlex.quote(f"cat {remote_path} 2>/dev/null; rm -f {remote_path}")
        try:
            contents = self.run(
                build_remote_experiment_command(self.app, f"sh -c {move}")
            )
        except RuntimeError as e:
            logger.warning(f"Could not copy the bot log from {remote_path}: {e}")
            return
        if self.bot_log_file is not None and contents:
            self.bot_log_file.write(contents)
            self.bot_log_file.flush()


class RemoteSqlError(RuntimeError):
    """A statement that ``psql`` ran on the server failed; ``pgcode`` is its SQLSTATE, if known."""

    def __init__(self, message, pgcode=None):
        super().__init__(message)
        self.pgcode = pgcode


def _app_postgres_container(executor, app):
    """Return the app's PostgreSQL container.

    Newer Dallinger versions give an app its own ``<app>_postgresql``
    container; other apps use the server's shared ``dallinger-postgresql-1``.
    A stopped own container is an error rather than a reason to fall back,
    because the shared one doesn't hold the app's database.

    Raises
    ------
    ValueError
        If no container is found, or the app's own one isn't running.
    """

    def inspect(container, field):
        output = executor.run(
            f"docker inspect -f '{field}' {shlex.quote(container)}", raise_=False
        )
        return (output or "").strip()

    own = f"{app}_postgresql"
    for container in (own, _SHARED_POSTGRES):
        if inspect(
            container, "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}"
        ):
            return container
        if container == own and inspect(container, "{{.Id}}"):
            raise ValueError(
                f"The PostgreSQL container {own} exists but isn't running; "
                "start the app again."
            )
    raise ValueError(f"Could not find a PostgreSQL container for the app {app}.")


class DatabaseReset:
    """Reset an SSH app's database to a snapshot before each test of a suite.

    It is the suite's ``before_test`` hook (see
    :class:`psynet.perf_test.PerformanceSuite`). The first call pre-fills the
    database if asked, waits for async jobs to finish, and takes the snapshot
    with ``CREATE DATABASE ... TEMPLATE``, a file-level copy that keeps
    sequences, indexes and table bloat. Every later call drops the database
    and creates it again from the snapshot. :meth:`close` restores the
    database to how the run found it, so that every run starts from the same
    data, and drops the snapshot. When pre-filling, the first call also
    copies the database before the pre-fill, and :meth:`close` restores that
    copy.

    PostgreSQL only copies or drops a database that nobody is connected to,
    so each call stops the app's server processes (:meth:`RemoteApp.stop`),
    terminates the connections that remain, and starts the processes again
    afterwards, which also empties their in-memory caches. It deletes the RQ
    job keys from Redis, because jobs refer to rows by ID, but keeps the
    other keys, such as the launch flags without which the app would launch
    the experiment again. Files that tests add to the asset storage remain;
    only the rows that refer to them go.

    Parameters
    ----------
    remote : RemoteApp
        The app.
    prefill_participants : int, optional
        Bots to run through the experiment before the snapshot is taken, so
        that every test starts with their data.

    Raises
    ------
    ValueError
        If the app's PostgreSQL container can't be found, or the web
        container's database isn't the app's own.
    """

    def __init__(self, remote, prefill_participants=None):
        self.remote = remote
        self.database = remote.app
        # The first check that the database may be reset, before anything changes.
        remote.prepare()
        name = remote.database_name()
        if name != self.database or name in _SYSTEM_DATABASES:
            raise ValueError(
                f"Refusing to reset the database {name!r}: performance tests only "
                f"reset the app's own database, which is named after the app "
                f"({self.database})."
            )
        self.container = _app_postgres_container(remote.executor, remote.app)
        self._prefill_participants = prefill_participants
        self.snapshot = None
        # Rows in each growing table of the snapshot, once taken.
        self.snapshot_rows = None
        # Every copy, named before it is made, so that close() drops interrupted ones.
        self._copies = []
        # The complete copy of the database as the run found it.
        self._original = None

    def __call__(self):
        """Take or restore the snapshot, with the app's server processes stopped meanwhile.

        They start again afterwards. If taking or restoring the snapshot
        fails, they stay stopped and the error propagates; the caller then
        calls :meth:`close` and :meth:`RemoteApp.start_stopped_services`.
        """
        if self.snapshot is not None:
            logger.info("")
            logger.info(f"Resetting the database to {self.snapshot}...")
            self._restore(self.snapshot)
            return
        if self._prefill_participants:
            # The copy clears the job queues, which would orphan unfinished jobs.
            self._check_no_async_jobs_waiting(
                self.remote.prepare(async_timeout_s=_ASYNC_DRAIN_TIMEOUT_S),
                "the database was not copied before pre-filling it",
            )
            logger.info("")
            logger.info("Copying the database before pre-filling it...")
            self._original = self._take_copy("baseline")
        self._check_no_async_jobs_waiting(
            self.remote.prepare(
                prefill_participants=self._prefill_participants,
                async_timeout_s=_ASYNC_DRAIN_TIMEOUT_S,
            ),
            "no snapshot was taken",
        )
        logger.info("")
        logger.info("Taking a snapshot of the database...")
        self.snapshot = self._take_copy("snapshot")
        self._original = self._original or self.snapshot

        from psynet.perf_test.measure import database_rows

        self.snapshot_rows = database_rows(self._cursor(self.database))
        rows = ", ".join(f"{t} {n:,}" for t, n in self.snapshot_rows.items())
        logger.info(f"Snapshot {self.snapshot}: {rows} rows.")
        n_participants = self.snapshot_rows.get("participant", 0)
        if not self._prefill_participants and n_participants:
            logger.warning(
                warning(
                    f"The database already held {n_participants:,} "
                    "participants when the snapshot was taken, for example "
                    "from manual testing or a run that couldn't restore it, so "
                    "every test starts from that data rather than from a fresh "
                    "database. To start fresh, destroy the app with 'psynet "
                    f"destroy ssh --server {self.remote.server} --app "
                    f"{self.database}'; the next 'psynet performance-test ssh' "
                    "deploys it again with an empty database."
                )
            )

    @staticmethod
    def _check_no_async_jobs_waiting(waiting, consequence):
        """Raise ``RuntimeError`` if ``waiting`` async jobs are still unfinished."""
        if waiting:
            raise RuntimeError(
                f"{waiting:,} async jobs had not finished after "
                f"{_ASYNC_DRAIN_TIMEOUT_S // 60} minutes, so {consequence}: "
                "their jobs would be lost at each reset. Check the "
                "experiment's async jobs in the server log."
            )

    def close(self):
        """Restore the database to how the run found it, then drop the copies.

        The app's server processes stay stopped afterwards, for
        :meth:`RemoteApp.start_stopped_services` to start. A copy that can't
        be dropped only causes a warning.

        Raises
        ------
        BaseException
            The restore's error, including an interruption, after the other
            copies are dropped. The warning before it names the copy that
            the restore read from, which is kept, and says how to recover.
        """
        import click

        kept = None
        restore_error = None
        if self._original is not None:
            logger.info("")
            logger.info("Restoring the database to how it was before the run...")
            try:
                self._restore(self._original, start=False)
            except BaseException as e:
                self._warn_restore_failed(e)
                kept, restore_error = self._original, e
        for copy in self._copies:
            if copy == kept:
                continue
            try:
                self._run_when_unused(
                    copy, f"DROP DATABASE IF EXISTS {_quote_ident(copy)}"
                )
            except (click.Abort, click.exceptions.Exit):
                raise
            except RuntimeError as e:
                logger.warning(
                    warning(
                        f"Could not drop the database {copy} ({e}). Drop it on "
                        f"{self.remote.server} with: docker exec {self.container} "
                        f"sh -c 'dropdb -U \"$POSTGRES_USER\" {copy}'"
                    )
                )
        if restore_error is not None:
            raise restore_error

    def _warn_restore_failed(self, error):
        """Warn that the database couldn't be restored from the original copy, and how to recover by redeploying the app."""
        logger.warning(
            warning(
                f"Could not restore the database {self.database} to how it was "
                f"before the run ({str(error) or type(error).__name__}), so the "
                f"next run would start from this run's data. {self._original} "
                "keeps the database as the run found it. To recover, destroy the "
                f"app with 'psynet destroy ssh --server {self.remote.server} --app "
                f"{self.database}' and run the same 'psynet performance-test ssh' "
                "command again, which deploys it afresh. With classic ingress, "
                f"destroying the app leaves {self._original} in the shared "
                f"PostgreSQL container; drop it with: docker exec {self.container} "
                f"sh -c 'dropdb -U \"$POSTGRES_USER\" {self._original}'"
            )
        )

    def _take_copy(self, kind):
        """Copy the database to a new ``<app>_<kind>_<time>`` database with the server processes stopped, and return its name."""
        stamp = f"_{kind}_{datetime.datetime.now():%Y%m%d%H%M%S%f}"
        name = self.database[: _MAX_NAME_LENGTH - len(stamp)] + stamp
        # Recorded before copying, so that close() drops an interrupted copy.
        self._copies.append(name)
        self.remote.stop()
        try:
            self._copy(self.database, name)
        except RemoteSqlError as e:
            if e.pgcode == _DUPLICATE_DATABASE:
                self._copies.remove(name)
            raise
        self.remote.clear_job_queues()
        self.remote.start()
        return name

    def _restore(self, source, start=True):
        """Recreate the database from database ``source`` with the server processes stopped.

        They may already be stopped by a reset that failed. They start
        again afterwards if ``start``.
        """
        if not self.remote._stopped:
            # The final restore needn't pass the check again, which needs the web server.
            self.remote.stop(check=start)
        self._check_disk_space(source)
        self._run_when_unused(
            self.database, f"DROP DATABASE IF EXISTS {_quote_ident(self.database)}"
        )
        self._copy(source, self.database)
        self.remote.clear_job_queues()
        if start:
            self.remote.start()

    def _cursor(self, database="postgres"):
        return _PsqlCursor(self.remote.executor, self.container, database)

    def _copy(self, source, name):
        """Create database ``name`` as a copy of database ``source``."""
        self._check_disk_space(source)
        self._run_when_unused(
            source,
            f"CREATE DATABASE {_quote_ident(name)} TEMPLATE {_quote_ident(source)}",
        )

    def _check_disk_space(self, source):
        """Raise unless PostgreSQL's data directory has twice the size of database ``source`` free."""
        cursor = self._cursor()
        cursor.execute(f"SELECT pg_database_size({_quote_literal(source)})")
        needed = 2 * int(cursor.fetchone()[0])
        cursor.execute("SHOW data_directory")
        directory = cursor.fetchone()[0]
        cmd = (
            f"docker exec {shlex.quote(self.container)} df -Pk {shlex.quote(directory)}"
        )
        try:
            free = int(self.remote.run(cmd).splitlines()[-1].split()[3]) * 1024
        except (RuntimeError, IndexError, ValueError) as e:
            raise RuntimeError(
                f"Could not read the free disk space of {directory} in "
                f"{self.container}, so the database is not copied: {e}"
            ) from e
        if free < needed:
            raise RuntimeError(
                f"Copying {source} needs about {_size(needed)} of free disk space "
                f"(PsyNet asks for twice the database's size), but {directory} has "
                f"only {_size(free)} free."
            )

    def _run_when_unused(self, database, statement):
        """Run ``statement`` after terminating the client connections to ``database``.

        Retries if a client connects again in between, or autovacuum briefly
        holds the database.
        """
        cursor = self._cursor()
        for attempt in range(_IN_USE_ATTEMPTS):
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = {_quote_literal(database)} "
                "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
            )
            try:
                cursor.execute(statement)
                return
            except RemoteSqlError as e:
                if e.pgcode != _OBJECT_IN_USE or attempt == _IN_USE_ATTEMPTS - 1:
                    raise
            time.sleep(1)


class _PsqlCursor:
    """The part of a DB-API cursor that :func:`~psynet.perf_test.measure.database_rows` uses, running ``psql`` in a container.

    Each statement runs on its own, in autocommit mode, as the container's
    ``POSTGRES_USER`` over the container's local socket. Values come back
    as strings, and NULL as ``None``.
    """

    def __init__(self, executor, container, database):
        self._executor = executor
        self._container = container
        self._database = database
        self._rows = []

    def execute(self, statement):
        psql = shlex.quote('PGUSER="$POSTGRES_USER" exec psql "$@"')
        # English messages, so that _SQLSTATE finds the error code.
        options = shlex.quote("PGOPTIONS=-cclient_min_messages=warning -clc_messages=C")
        cmd = (
            f"docker exec -e {options} -e LC_MESSAGES=C "
            f"{shlex.quote(self._container)} sh -c {psql} psql "
            "-X -q -t --csv -v ON_ERROR_STOP=1 -v VERBOSITY=verbose "
            f"-d {shlex.quote(self._database)} -c {shlex.quote(statement)}"
        )
        status, output = run_with_status(self._executor, cmd)
        if status:
            match = _SQLSTATE.search(output)
            raise RemoteSqlError(output.strip(), match[1] if match else None)
        self._rows = [
            tuple(None if value == "" else value for value in row)
            for row in csv.reader(io.StringIO(output))
            if row
        ]

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows


def _quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(value):
    # PostgreSQL's standard_conforming_strings (on by default) keeps backslashes literal.
    return "'" + str(value).replace("'", "''") + "'"


def _size(n_bytes):
    return f"{n_bytes / 1e9:,.1f} GB" if n_bytes >= 1e9 else f"{n_bytes / 1e6:,.0f} MB"


def _performance_test_flags(**options):
    """Return ``performance-test`` command-line flags for ``options``, preserving explicit zeros.

    ``options`` are named like the command's options, e.g. ``n_bots`` for
    ``--n-bots``; a list becomes a comma-separated value. The result starts
    with a space unless it is empty.
    """
    flags = ""
    for name, value in options.items():
        if isinstance(value, list):
            value = ",".join(str(v) for v in value)
        flag = f"--{name.replace('_', '-')}"
        if value is True:
            flags += f" {flag}"
        elif value is not None and value is not False:
            flags += f" {flag} {shlex.quote(str(value))}"
    return flags


class RemotePerformanceTester:
    """Run each test as its own ``psynet performance-test local --existing`` in the app's web container.

    It has the interface of :class:`psynet.perf_test.PerformanceTester` that
    :class:`psynet.perf_test.PerformanceSuite` uses, so the suite runs on
    this computer while the bots run on the server.

    Parameters
    ----------
    remote : RemoteApp
        The app.
    duration_minutes, stagger_interval_s, time_factor : float
        As for :class:`~psynet.perf_test.PerformanceTester`.
    bot_processes : int or "auto"
        As for :class:`~psynet.perf_test.PerformanceTester`; ``"auto"``
        plans for each test's own bot count.
    estimated_duration_minutes, arrival_minutes : float, optional
        As for :class:`~psynet.perf_test.PerformanceTester`.
    """

    def __init__(
        self,
        remote,
        *,
        duration_minutes,
        stagger_interval_s,
        time_factor,
        bot_processes,
        estimated_duration_minutes=None,
        arrival_minutes=None,
    ):
        self.remote = remote
        self.duration_minutes = duration_minutes
        self.stagger_interval_s = stagger_interval_s
        self.time_factor = time_factor
        self.bot_processes = bot_processes
        self.estimated_duration_minutes = estimated_duration_minutes
        self.arrival_minutes = arrival_minutes
        #: The JSON metadata of the first remote test, such as the server's PsyNet version.
        self.remote_metadata = None
        self._suite_started = None
        self._pause_before_test = False

    session_minutes = PerformanceTester.session_minutes

    @contextmanager
    def bot_runner(self, max_bots, bot_log_file):
        """Note when the suite starts: each remote test starts and stops its own bot processes."""
        self._suite_started = time.monotonic()
        yield

    def pause_between_tests(self):
        """Make the next remote test pause first, as a local suite pauses between tests."""
        self._pause_before_test = True

    def run_test(
        self, title, n_bots, bot_log_file, duration_minutes, arrival_minutes=None
    ):
        """Run one test of ``n_bots`` bots on the server and return its result.

        The arguments are as for :meth:`psynet.perf_test.PerformanceTester.run_test`.
        After :meth:`pause_between_tests`, it pauses first and waits for async
        jobs that the suite's earlier tests queued.
        """
        suite_started_s_ago = None
        if self._pause_before_test:
            self._pause_before_test = False
            suite_started_s_ago = round(time.monotonic() - self._suite_started)
        args = "performance-test local --existing" + _performance_test_flags(
            n_bots=[n_bots],
            test_label=title,
            suite_started_s_ago=suite_started_s_ago,
            duration_minutes=duration_minutes,
            arrival_minutes=arrival_minutes,
            stagger=self.stagger_interval_s,
            time_factor=self.time_factor,
            bot_processes=self.bot_processes,
            force=self.remote.force,
        )
        payload = self.remote.run_psynet(args, bot_log=True)
        if self.remote_metadata is None:
            self.remote_metadata = {
                k: v for k, v in payload.items() if k not in ("options", "results")
            }
        return PerformanceTestResult.from_dict(payload["results"][0])
