"""Reset and pre-fill the database of an SSH app for ``psynet performance-test ssh``.

Without a reset, ``performance-test ssh`` runs the whole suite as one
``psynet performance-test local --existing`` inside the app's web container.
A reset has to stop that container, which would stop the test with it, so
with ``--reset-database`` this computer drives the suite instead: each test
is its own ``performance-test local --existing`` in the web container, whose
JSON result is read back, and between tests :class:`RemoteApp` stops the
app's server processes, :class:`psynet.perf_reset.DatabaseReset` restores
the snapshot, and the processes start again. :class:`RemotePerformanceTester`
is the tester that :class:`psynet.perf_test.PerformanceSuite` sees, so the
capacity search and summaries are those of a local run.

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
  container's superuser (:class:`RemoteAppDatabase`), never through an SSH
  tunnel, so the database is never reached as if it were local.
- Only the app's own database is reset, and only snapshots named after the
  app (``psynet_prefill_<app>_<code>_n<N>``) are listed or dropped, so apps
  that share a PostgreSQL never see each other's snapshots. The database
  name comes from the web container's ``DATABASE_URL`` and must be the app
  name; the PostgreSQL container is the one Dallinger's export finds for
  the app.
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
- Secrets in the containers' environments never leave the server: commands
  print only what they need, such as the database name.
"""

import csv
import io
import json
import logging
import re
import shlex
import time
import uuid
from contextlib import contextmanager

import psycopg2

from psynet.perf_reset import SYSTEM_DATABASES, SnapshotDatabase

logger = logging.getLogger(__name__)

_STATUS_MARKER = "__psynet_exit_status="
_SHARED_POSTGRES = "dallinger-postgresql-1"
_KEPT_SERVICES = frozenset(
    {"postgresql", "redis", "frontdoor", "controller", "cloudflared"}
)
_SERVER_READY_TIMEOUT_S = 180
_SQLSTATE = re.compile(r"ERROR:\s+([0-9A-Z]{5}):")
_HEALTH_PROBE = (
    "import urllib.request; "
    "urllib.request.urlopen('http://localhost:5000/health', timeout=10)"
)


def run_with_status(executor, cmd):
    """Run shell command ``cmd`` on the server; return its exit status and output.

    The output is the command's stdout, followed by its stderr only if it
    fails, so that warnings on stderr, such as Docker Compose's, can't
    corrupt output that is parsed, and errors still say what went wrong.
    """
    script = (
        f'err=$(mktemp) && {{ {cmd} ; }} 2>"$err"; status=$?; '
        '[ "$status" -eq 0 ] || cat "$err"; rm -f "$err"; '
        f"echo {_STATUS_MARKER}$status"
    )
    output = executor.run(script, raise_=False)
    output, _, status = (output or "").rpartition(_STATUS_MARKER)
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
        # Services that stop() stopped, until start() has the server ready again.
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
        click.Abort
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
        """Check that the app's database may be reset, optionally pre-fill it, and return facts about it.

        This runs ``psynet performance-test prepare-reset`` in the web
        container, which refuses an app that ``performance-test ssh`` didn't
        deploy or that runs in live mode and, unless
        :attr:`force`, one that has non-bot participants or a recruiter that
        may bring real ones. Then it adds ``prefill_participants`` bots'
        data, and waits up to ``async_timeout_s`` for async processes to
        finish.

        Returns
        -------
        dict
            The experiment's ``label``, ``test_n_bots``,
            ``test_duration_minutes`` and ``test_parallel_stagger_interval_s``,
            and the number of async processes still ``waiting``.
        """
        args = "performance-test prepare-reset"
        if self.force:
            args += " --force"
        if prefill_participants:
            args += f" --prefill-participants {int(prefill_participants)}"
        if async_timeout_s is not None:
            args += f" --wait-for-async-processes {int(async_timeout_s)}"
        return self.run_psynet(args, bot_log=bool(prefill_participants))

    def database_name(self):
        """Return the name of the database in the web container's ``DATABASE_URL``."""
        probe = (
            "import os, urllib.parse; "
            "print(urllib.parse.urlsplit(os.environ['DATABASE_URL']).path.lstrip('/'))"
        )
        return self.compose("exec", "-T", "web", "python", "-c", probe).strip()

    def stop(self):
        """Check that the database may be reset, then stop the app's running or restarting services that may use the database.

        Those are all except PostgreSQL, Redis and the front door's
        services; :meth:`start` starts them again.

        Raises
        ------
        RuntimeError
            If none of them runs: without services, ``docker compose stop``
            would stop every service, PostgreSQL and Redis included.
        """
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
            If the server isn't ready within ``_SERVER_READY_TIMEOUT_S``.
        """
        print(f"▶ Starting {self.app}'s server processes...")
        if self._stopped:
            self.compose("start", *self._stopped)
        deadline = time.monotonic() + _SERVER_READY_TIMEOUT_S
        health = " ".join(
            [self._compose, "exec -T web python -c", shlex.quote(_HEALTH_PROBE)]
        )
        while True:
            healthy = run_with_status(self.executor, health)[0] == 0
            if (
                healthy
                and int(self._redis("SCARD", "rq:workers") or 0) >= self._n_workers
            ):
                self._stopped = []
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"{self.app} was not ready {_SERVER_READY_TIMEOUT_S} s after its "
                    "server processes started; see its logs in Dozzle."
                )
            time.sleep(2)

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
            print(
                f"✗ {self.app} may be stopped: its server processes could not be "
                f"started again ({str(e) or type(e).__name__}). Start them on "
                f"{self.server} with:\n    {command}\nIf the app still doesn't "
                "work, for example because the reset had dropped its database, "
                "redeploy it."
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


class RemoteSqlError(psycopg2.Error):
    """A statement that ``psql`` ran on the server failed.

    It is a :class:`psycopg2.Error`, with the SQLSTATE in ``pgcode``, so
    that :mod:`psynet.perf_reset` handles it like a local error.
    """

    def __init__(self, message, sqlstate=None):
        super().__init__(message)
        self._sqlstate = sqlstate

    @property
    def pgcode(self):
        return self._sqlstate


def _app_postgres_container(executor, app):
    """Return the app's PostgreSQL container and whether it is the app's own.

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
            return container, container == own
        if container == own and inspect(container, "{{.Id}}"):
            raise ValueError(
                f"The PostgreSQL container {own} exists but isn't running; "
                "start the app again."
            )
    raise ValueError(f"Could not find a PostgreSQL container for the app {app}.")


class RemoteAppDatabase(SnapshotDatabase):
    """The database of an app on an SSH server, reached with ``docker exec ... psql``.

    The database is named after the app, as Dallinger names it; its
    PostgreSQL container is the app's own or the server's shared one.

    Parameters
    ----------
    remote : RemoteApp
        The app.

    Raises
    ------
    ValueError
        If the app's PostgreSQL container can't be found or isn't running.
    """

    def __init__(self, remote):
        self.container, self.isolated = _app_postgres_container(
            remote.executor, remote.app
        )
        self.remote = remote
        super().__init__(
            remote.app,
            f"psynet_prefill_{remote.app}_",
            "psynet performance-test snapshots "
            f"--server {remote.server} --app {remote.app}",
        )

    def check_resettable(self):
        """Raise ``ValueError`` unless the web container's database is the app's own."""
        name = self.remote.database_name()
        if name != self.name or name in SYSTEM_DATABASES or name == "dallinger":
            raise ValueError(
                f"Refusing to reset the database {name!r}: performance tests only "
                f"reset the app's own database, which is named after the app "
                f"({self.name})."
            )

    def prefill_snapshot_name(self, code_key, n_participants):
        """Return the snapshot name, which includes the app name.

        Raises
        ------
        ValueError
            If the name would be longer than PostgreSQL's 63 characters.
        """
        name = super().prefill_snapshot_name(code_key, n_participants)
        if len(name) > 63:
            raise ValueError(
                f"The app name {self.name} is too long for the pre-fill snapshot "
                f"name {name}, which PostgreSQL would cut to 63 characters; use a "
                "shorter app name."
            )
        return name

    @contextmanager
    def cursor(self, database="postgres"):
        """Yield a cursor whose statements run with ``psql`` in the PostgreSQL container."""
        yield _PsqlCursor(self.remote.executor, self.container, database)

    def free_disk_space(self, directory):
        """Return the free bytes of ``directory`` in the PostgreSQL container.

        Raises
        ------
        RuntimeError
            If ``df`` fails, so that the reset refuses rather than risks
            filling the server's disk.
        """
        cmd = (
            f"docker exec {shlex.quote(self.container)} df -Pk {shlex.quote(directory)}"
        )
        try:
            return int(self.remote.run(cmd).splitlines()[-1].split()[3]) * 1024
        except (RuntimeError, IndexError, ValueError) as e:
            raise RuntimeError(
                f"Could not read the free disk space of {directory} in "
                f"{self.container}, so the database is not copied: {e}"
            ) from e

    def clear_job_queues(self):
        self.remote.clear_job_queues()

    def wait_for_async_processes(self, timeout_s):
        return self.remote.prepare(async_timeout_s=timeout_s)["waiting"]

    def drop_hint(self, name):
        return (
            f"Drop it on {self.remote.server} with: docker exec {self.container} "
            f"sh -c 'dropdb -U \"$POSTGRES_USER\" {name}'"
        )


class _PsqlCursor:
    """The part of a psycopg2 cursor that :mod:`psynet.perf_reset` uses, running ``psql`` in a container.

    Each statement runs on its own, in autocommit mode, as the container's
    ``POSTGRES_USER`` over the container's local socket. Values come back
    as strings, and NULL as ``None``.
    """

    def __init__(self, executor, container, database):
        self._executor = executor
        self._container = container
        self._database = database
        self._rows = []

    def execute(self, statement, params=None):
        query = _render(statement, params)
        psql = shlex.quote('PGUSER="$POSTGRES_USER" exec psql "$@"')
        cmd = (
            "docker exec -e PGOPTIONS=-cclient_min_messages=warning "
            f"{shlex.quote(self._container)} sh -c {psql} psql "
            "-X -q -t --csv -v ON_ERROR_STOP=1 -v VERBOSITY=verbose "
            f"-d {shlex.quote(self._database)} -c {shlex.quote(query)}"
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


def _render(statement, params=None):
    """Return ``statement``, a string or :mod:`psycopg2.sql` object, as SQL text with ``params`` filled in."""
    from psycopg2 import sql

    if isinstance(statement, sql.Composed):
        text = "".join(_render(part) for part in statement.seq)
    elif isinstance(statement, sql.SQL):
        text = statement.string
    elif isinstance(statement, sql.Identifier):
        text = ".".join('"' + s.replace('"', '""') + '"' for s in statement.strings)
    elif isinstance(statement, sql.Literal):
        text = _literal(statement.wrapped)
    else:
        text = statement
    if params is not None:
        text = text % tuple(_literal(value) for value in params)
    return text


def _literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    # PostgreSQL's standard_conforming_strings (on by default) keeps backslashes literal.
    return "'" + str(value).replace("'", "''") + "'"


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
    """

    def __init__(
        self,
        remote,
        *,
        duration_minutes,
        stagger_interval_s,
        time_factor,
        bot_processes,
    ):
        self.remote = remote
        self.duration_minutes = duration_minutes
        self.stagger_interval_s = stagger_interval_s
        self.time_factor = time_factor
        self.bot_processes = bot_processes
        #: The JSON metadata of the first remote test, such as the server's PsyNet version.
        self.remote_metadata = None

    @contextmanager
    def bot_runner(self, max_bots, bot_log_file):
        """Do nothing: each remote test starts and stops its own bot processes."""
        yield

    def pause_between_tests(self):
        time.sleep(5)

    def release_database_connections(self):
        """Do nothing: the bots' connections close when their remote test ends."""

    def run_test(self, label, n_bots, bot_log_file):
        """Run one test of ``n_bots`` bots on the server and return its result."""
        from psynet.command_line import performance_test_flags
        from psynet.perf_test import PerformanceTestResult

        args = "performance-test local --existing" + performance_test_flags(
            n_bots=[n_bots],
            test_label=label,
            duration_minutes=self.duration_minutes,
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
