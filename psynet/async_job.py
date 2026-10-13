"""Database-backed jobs that run a function outside the current request.

An :class:`AsyncJob` stores a function and its arguments as a row in the
``async_job`` table, so that slow work (e.g. ``async_post_trial``, asset
deposits, or :class:`~psynet.timeline.AsyncCodeBlock` functions) can run
without blocking the participant's request. :class:`WorkerAsyncJob` runs the
function on an RQ worker and supports timeouts and cancellation;
:class:`LocalAsyncJob` runs it in a thread of the current process.

Constructing a job does not run it. Call :meth:`AsyncJob.enqueue`, which adds
the job to the database session and launches it only once the transaction
commits, so the job never starts before the rows it depends on are saved,
and a rolled-back transaction launches nothing. A job that is created but
never enqueued is reported with a warning when its transaction commits.

Jobs are linked to the objects they work on (participant, trial, node,
network, response, asset) through the ``async_jobs`` relationships on those
models. When a job fails, :attr:`AsyncJob.failure_cascade` fails its trial
and node, and the error is recorded as an :class:`~psynet.error.ErrorRecord`
pointing at the job.

A :class:`WorkerAsyncJob` has a priority, ``"high"`` or ``"low"``, naming the
RQ queue it is enqueued on; workers take jobs from the ``high`` queue first.
"""

import datetime
import threading
import time
import warnings
from contextvars import ContextVar
from functools import partial

import dallinger.db
from dallinger import db
from dallinger.db import redis_conn
from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job, JobStatus
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    and_,
    func,
    inspect,
    or_,
)
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import deferred, relationship
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_exponential

from .data import SQLBase, SQLMixin, register_table
from .db import (
    _call_after_commit,
    _SessionQueue,
    _set_transaction_lock_timeout,
    with_transaction,
)
from .field import PythonDict, PythonObject
from .notifier import _send_alert
from .serialize import prepare_function_for_serialization
from .utils import get_logger

logger = get_logger()

_RECHECK_LOCK_TIMEOUT_SECONDS = 5

PRIORITIES = ("high", "low")


def check_priority(priority):
    """Raise ``ValueError`` unless ``priority`` is one of :data:`PRIORITIES`."""
    if priority not in PRIORITIES:
        raise ValueError(
            f"Invalid async job priority {priority!r}; expected one of {PRIORITIES}."
        )


_running_async_job = ContextVar("psynet_running_async_job", default=False)


def _in_async_job():
    """Whether the current code runs inside an async job's function.

    The job's own trial is finalized by :meth:`Trial.recheck_finalization`
    after the job commits, which locks the participant before the trial;
    other trials touched there are left to :meth:`Trial.finalize_pending_trials`.
    Finalizing inside the job would lock the trial first, and a request
    holding the participant could then deadlock with it.
    """
    return _running_async_job.get()


def _get_async_processes(obj):
    warnings.warn(
        f"{type(obj).__name__}.async_processes has been renamed to async_jobs.",
        DeprecationWarning,
        stacklevel=2,
    )
    return obj.async_jobs


_deprecated_async_processes = property(
    _get_async_processes,
    doc="Deprecated alias of ``async_jobs``.",
)


def _warn_unenqueued(entries):
    for job, label in entries:
        identity = inspect(job).identity
        logger.warning(
            "Async job %s (label %r) was created but never enqueued, so it "
            "will not run. Call .enqueue() on the job to run it.",
            identity[0] if identity else "(unsaved)",
            label,
        )


_unenqueued_jobs = _SessionQueue(
    "unenqueued_async_jobs", list, on_commit=_warn_unenqueued
)


@register_table
class AsyncJob(SQLBase, SQLMixin):
    """A function call that runs asynchronously once its transaction commits.

    Use a subclass, :class:`WorkerAsyncJob` or :class:`LocalAsyncJob`, and
    call :meth:`enqueue` to run the job.

    Parameters
    ----------
    function : callable
        The function to call. Instance methods of database objects are
        supported; the object is reloaded in the job's session.
    arguments : dict, optional
        Keyword arguments for ``function``.
    trial, response, participant, node, network, asset : optional
        Objects the job works on. They are linked to the job through their
        ``async_jobs`` relationships, and the participant and trial maker are
        inferred from them when not given.
    label : str, optional
        A label for the job; defaults to the function's name.
    unique : bool or dict, optional
        If ``True``, enqueueing fails with an ``IntegrityError`` when a job
        with the same label, function and arguments already exists. A dict
        is used as the uniqueness key instead.
    priority : str, optional
        ``"high"`` or ``"low"``; see :class:`WorkerAsyncJob`. It is stored
        on a :class:`LocalAsyncJob` too, but has no effect there.

    Attributes
    ----------
    time_taken : float
        Wall-clock seconds the job took to run.
    queue_delay : float
        Seconds between enqueueing the job and the job starting.
    cpu_time : float
        CPU seconds used by the job's thread while its function ran,
        measured with :func:`time.thread_time`. CPU used by other processes,
        such as the database server, is not counted. In a gevent worker the
        measurement also counts other greenlets that ran while this job
        waited on I/O, so it is exact for jobs that run alone and an upper
        bound when jobs overlap.
    """

    __tablename__ = "async_job"

    label = Column(String)
    function = Column(PythonObject)
    arguments = deferred(Column(PythonDict))
    pending = Column(Boolean)
    finished = Column(Boolean, default=False)
    time_enqueued = Column(DateTime)
    time_started = Column(DateTime)
    time_finished = Column(DateTime)
    time_taken = Column(Float)
    queue_delay = Column(Float)
    cpu_time = Column(Float)
    priority = Column(String)
    _unique_key = Column(PythonDict, unique=True)

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant",
        backref="async_jobs",
        foreign_keys=[participant_id],
    )

    trial_maker_id = Column(String, index=True)

    network_id = Column(Integer, ForeignKey("network.id"), index=True)
    network = relationship("TrialNetwork", back_populates="async_jobs")

    node_id = Column(Integer, ForeignKey("node.id"), index=True)
    node = relationship("TrialNode", back_populates="async_jobs")

    trial_id = Column(Integer, ForeignKey("trial.id"), index=True)
    trial = relationship("psynet.trial.main.Trial", back_populates="async_jobs")

    response_id = Column(Integer, ForeignKey("response.id"), index=True)
    response = relationship("psynet.timeline.Response", back_populates="async_jobs")

    asset_id = Column(Integer, ForeignKey("asset.id"), index=True)
    asset = relationship("Asset", back_populates="async_jobs")

    errors = relationship("ErrorRecord")

    def __init__(
        self,
        function,
        arguments=None,
        trial=None,
        response=None,
        participant=None,
        node=None,
        network=None,
        asset=None,
        label=None,
        unique=False,
        priority=None,
    ):
        if priority is not None:
            check_priority(priority)
        self.priority = priority

        if label is None:
            label = function.__name__

        if arguments is None:
            arguments = {}

        db.session.flush()

        function, arguments = prepare_function_for_serialization(function, arguments)

        self.label = label
        self.function = function
        self.arguments = arguments

        self.asset = asset
        if asset:
            self.asset_id = asset.id

        self.participant = participant
        if participant:
            self.participant_id = participant.id

        self.network = network
        if network:
            self.network_id = network.id

        self.node = node
        if node:
            self.node_id = node.id

        self.trial = trial
        if trial:
            self.trial_id = trial.id

        self.response = response
        if response:
            self.response_id = response.id

        self.infer_participant()
        self.infer_trial_maker_id()
        self.pending = True

        if unique:
            if isinstance(unique, bool):
                self._unique_key = {
                    "label": label,
                    "function": function,
                    "arguments": arguments,
                }
            else:
                self._unique_key = unique

        _unenqueued_jobs.get().append((self, label))

    def enqueue(self):
        """Save the job and launch it once the current transaction commits.

        If the transaction rolls back, the job is discarded and never
        launched.

        Returns
        -------
        AsyncJob
            The job itself, so it can be enqueued as it is created.

        Raises
        ------
        RuntimeError
            If the job has already been enqueued.
        sqlalchemy.exc.IntegrityError
            If the job was created with ``unique`` and a matching job exists.
        """
        if self.time_enqueued is not None:
            raise RuntimeError(f"Async job {self.id} has already been enqueued.")
        db.session.add(self)
        self.time_enqueued = datetime.datetime.now()
        _call_after_commit(partial(_launch_unless_cancelled, self.get_launch_spec()))
        unenqueued = _unenqueued_jobs.get()
        unenqueued[:] = [entry for entry in unenqueued if entry[0] is not self]
        return self

    def get_launch_spec(self) -> dict:
        db.session.flush([self])
        return {
            "obj": self,
            "class": self.__class__,
            "id": self.id,
        }

    def log_time_started(self):
        self.time_started = datetime.datetime.now()

    def log_time_finished(self):
        self.time_finished = datetime.datetime.now()

    def infer_participant(self):
        if self.participant is None:
            for obj in [self.asset, self.trial, self.node, self.network]:
                if obj and hasattr(obj, "participant") and obj.participant:
                    self.participant = obj.participant
                    break
            # For safety...
            if self.participant:
                self.participant_id = self.participant.id

    def infer_trial_maker_id(self):
        for obj in [self.trial, self.node, self.network]:
            if obj and obj.trial_maker_id:
                self.trial_maker_id = obj.trial_maker_id
                return

    @property
    def failure_cascade(self):
        """
        These are the objects that will be failed if the job fails. Ultimately we might want to
        add more objects to this list, for example participants, assets, and networks,
        but currently we're not confident that PsyNet supports failing those objects in that kind of way.
        An asset's job (e.g. an async deposit) fails the asset's trial, which could otherwise
        never be finalized; a trial that is already finalized is left alone.
        """
        trial = self.trial
        if trial is None and self.asset and self.asset.trial:
            trial = None if self.asset.trial.finalized else self.asset.trial
        candidates = [trial, self.node]
        return [lambda obj=obj: [obj] for obj in candidates if obj is not None]

    @classmethod
    def launch(cls, spec: dict):
        raise NotImplementedError

    @classmethod
    def call_function_with_logger(cls, async_job_id):
        cls.call_function(async_job_id)

    @classmethod
    @retry(
        retry=retry_if_exception_type(NoResultFound),
        wait=wait_exponential(multiplier=0.1, min=0.01),
        stop=stop_after_delay(4),
    )
    # The job gets launched when SQLAlchemy's after_commit event is triggered. This tells us when the COMMIT
    # has been issued to the database, but it does not guarantee that the commit has finished execution.
    # This is why we add some retry logic to ensure that the job is available in the database before continuing.
    def get_async_job(cls, async_job_id: int):
        return (
            AsyncJob.query.filter_by(id=async_job_id)
            .with_for_update(of=AsyncJob)
            .populate_existing()
            .one()
        )

    @classmethod
    def get_process(cls, process_id: int):
        """Deprecated alias of :meth:`get_async_job`."""
        warnings.warn(
            "AsyncJob.get_process has been renamed to get_async_job.",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls.get_async_job(process_id)

    @classmethod
    @with_transaction
    def call_function(cls, async_job_id):
        """
        Calls the defining function of a given async job.
        """
        print("\n")
        logger.info(f"Calling function for async job {async_job_id}...")

        job = None

        try:
            from psynet.experiment import get_experiment

            experiment = get_experiment()

            job = cls.get_async_job(async_job_id)
            if job.failed:
                logger.info(
                    "Async job %s has already failed or was cancelled; skipping.",
                    async_job_id,
                )
                job.pending = False
                return
            function = job.function

            arguments = cls.preprocess_args(job.arguments)

            timer = time.monotonic()
            job.log_time_started()
            if job.time_enqueued:
                job.queue_delay = (job.time_started - job.time_enqueued).total_seconds()
            db.session.commit()

            token = _running_async_job.set(True)
            cpu_timer = time.thread_time()
            try:
                function(**arguments)
            finally:
                _running_async_job.reset(token)

            job.cpu_time = time.thread_time() - cpu_timer
            job.time_finished = datetime.datetime.now()
            job.time_taken = time.monotonic() - timer
            job.pending = False
            job.finished = True

        except Exception as err:
            if not isinstance(err, experiment.HandledError):
                experiment.handle_error(err, async_job=job)

            if job:
                # We need to re-fetch the job because handle_error has done a rollback
                job = cls.get_async_job(async_job_id)
                job.pending = False
                job.fail(f"Exception in async job: {repr(err)}")

        finally:
            if job is not None and job.participant_id is not None:
                from psynet.timeline_hold import _queue_timeline_hold_wake

                _queue_timeline_hold_wake(
                    job.participant_id,
                    reason="async_job_finished",
                )
            trial_id = cls._get_trial_id(job)
            db.session.commit()

        if trial_id is not None:
            from psynet.trial.main import Trial

            try:
                # A busy participant should not tie up the worker; the
                # finalize backstop picks the trial up if this times out.
                _set_transaction_lock_timeout(_RECHECK_LOCK_TIMEOUT_SECONDS)
                Trial.recheck_finalization(trial_id)
                db.session.commit()
            except Exception:
                logger.warning(
                    "Post-commit finalize re-check failed for trial %s; "
                    "leaving it to the finalize backstop.",
                    trial_id,
                    exc_info=True,
                )
                db.session.rollback()

    @staticmethod
    def _get_trial_id(job):
        """Return the ID of the trial this job works on, if any."""
        if job is None:
            return None
        if job.trial_id is not None:
            return job.trial_id
        if job.asset is not None:
            return job.asset.trial_id
        return None

    @classmethod
    def preprocess_args(cls, arguments):
        """
        Preprocesses the arguments that are passed to the job's function.
        """
        return {key: cls.preprocess_arg(value) for key, value in arguments.items()}

    @classmethod
    def preprocess_arg(cls, arg):
        if isinstance(
            arg, dallinger.db.Base
        ):  # Tests if the object is an SQLAlchemy object
            arg = db.session.merge(arg)  # Reattaches the object to the database session
            db.session.refresh(arg)
        return arg


def _launch_unless_cancelled(spec):
    """Launch a committed job, unless it was cancelled before the commit."""
    # No SQL can run in after_commit, so read only already-loaded state; an
    # expired object here means a rolled-back change, so launch it.
    if inspect(spec["obj"]).dict.get("cancelled", False):
        return
    logger.info("Launching async job %s...", spec["id"])
    try:
        spec["class"].launch(spec)
    except Exception:
        logger.exception("Could not launch async job %s.", spec["id"])
        if issubclass(spec["class"], WorkerAsyncJob):
            consequence = (
                "so it stays pending until the clock fails it as lost, "
                "about an hour after it was enqueued."
            )
        else:
            consequence = "so it stays pending and will not run."
        _send_alert(
            f"Async job {spec['id']} ({spec['class'].__name__}) was "
            f"saved but could not be launched, {consequence}"
        )


CPU_HEAVY_RATIO = 0.5


def _get_cpu_time_summary():
    """Return CPU and wall times of finished async jobs.

    Jobs are grouped by where they run, label and priority. ``runs_in`` is
    ``"worker"`` for :class:`WorkerAsyncJob` and ``"web"`` for
    :class:`LocalAsyncJob`, which runs in a thread of the process that
    enqueued it, usually the web process, and has no priority.
    """
    keys = [
        "runs_in",
        "label",
        "priority",
        "count",
        "mean_cpu",
        "max_cpu",
        "mean_wall",
    ]
    summary = []
    for cls, runs_in in [(LocalAsyncJob, "web"), (WorkerAsyncJob, "worker")]:
        rows = (
            db.session.query(
                cls.label,
                cls.priority,
                func.count(cls.id),
                func.avg(cls.cpu_time),
                func.max(cls.cpu_time),
                func.avg(cls.time_taken),
            )
            .filter(
                cls.finished == True,  # noqa: E712
                cls.cpu_time != None,  # noqa: E711
                cls.time_taken != None,  # noqa: E711
            )
            .group_by(cls.label, cls.priority)
            .order_by(cls.label, cls.priority)
            .all()
        )
        summary += [dict(zip(keys, (runs_in, *row))) for row in rows]
    return summary


def _format_cpu_time_summary(rows):
    """Format the output of :func:`_get_cpu_time_summary` as a table.

    A row counts as CPU-heavy when its mean CPU time is at least
    ``CPU_HEAVY_RATIO`` of its mean wall time; such jobs need a CPU core
    each while they run, whereas I/O-bound jobs mostly wait. The "Runs in"
    column says whether that core is in a worker or the web process. Web
    jobs have no priority and show ``-``.
    """
    if not rows:
        return "No async jobs finished."
    header = [
        "Runs in",
        "Label",
        "Priority",
        "Count",
        "Mean CPU (s)",
        "Max CPU (s)",
        "Mean wall (s)",
        "CPU-heavy",
    ]
    table = [header]
    for row in rows:
        cpu_heavy = row["mean_cpu"] >= CPU_HEAVY_RATIO * row["mean_wall"]
        table.append(
            [
                row["runs_in"],
                row["label"],
                row["priority"] or "-",
                str(row["count"]),
                f"{row['mean_cpu']:.3f}",
                f"{row['max_cpu']:.3f}",
                f"{row['mean_wall']:.3f}",
                "yes" if cpu_heavy else "no",
            ]
        )
    widths = [max(len(cell) for cell in column) for column in zip(*table)]
    lines = [
        f"Async job CPU time (CPU-heavy: mean CPU >= {CPU_HEAVY_RATIO:.0%} "
        "of mean wall time):"
    ]
    for line in table:
        cells = [cell.ljust(width) for cell, width in zip(line[:3], widths[:3])]
        cells += [cell.rjust(width) for cell, width in zip(line[3:], widths[3:])]
        lines.append("  " + "  ".join(cells))
    return "\n".join(lines)


class LocalAsyncJob(AsyncJob):
    """An async job that runs in a new thread of the current process.

    Accepts the same parameters as :class:`AsyncJob`.
    """

    @classmethod
    def launch(cls, spec: dict):
        thr = threading.Thread(
            target=cls.thread_function, kwargs={"async_job_id": spec["id"]}
        )
        thr.start()

    @classmethod
    def thread_function(cls, async_job_id):
        try:
            cls.call_function_with_logger(async_job_id)
        finally:
            db.session.commit()
            db.session.close()


_RQ_LOST_STATUSES = {JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED}


def _rq_job_id(async_job_id):
    """Return the RQ job ID for an async job, so it can be found to cancel."""
    return f"psynet_async_job_{async_job_id}"


def _cancel_rq_job(async_job_id):
    """Cancel an async job's RQ job if it is still queued."""
    try:
        Job.fetch(_rq_job_id(async_job_id), connection=redis_conn).cancel()
    except (NoSuchJobError, InvalidJobOperation):
        logger.info(
            "No RQ job to cancel for async job %s; it expired, was already "
            "cancelled, or was never launched.",
            async_job_id,
        )
    except RedisError:
        logger.warning(
            "Could not cancel the RQ job of async job %s; the worker will "
            "skip it because the async job is marked cancelled.",
            async_job_id,
            exc_info=True,
        )


class WorkerAsyncJob(AsyncJob):
    """An async job that runs on an RQ worker.

    Accepts the parameters of :class:`AsyncJob`, plus:

    Parameters
    ----------
    timeout : float, optional
        Seconds after which the job fails if it has not finished, counted
        from when a worker starts running it. Time spent waiting in the
        queue does not count. A job that has not started within
        :attr:`max_queue_wait_sec` (1 hour) of being enqueued is failed only
        if RQ lost it.
    priority : str, default ``"high"``
        The RQ queue the job runs on, ``"high"`` or ``"low"``. Workers take
        jobs from the ``high`` queue before the ``low`` queue, but do not
        interrupt a running job: a high-priority job still waits for a free
        worker if every worker is busy.

    Attributes
    ----------
    max_queue_wait_sec : int
        Seconds after being enqueued (default 3600, i.e. 1 hour) after which
        :meth:`check_timeouts` fails a job that has not started, if RQ lost
        it: RQ no longer has the job, for example because its launch failed
        or Redis restarted, or RQ failed, stopped or cancelled it. A job
        still waiting in RQ is a genuine backlog and keeps waiting, and a job
        RQ reports as finished is left alone. A lost job is failed rather
        than re-run.
    """

    max_queue_wait_sec = 3600

    timeout = Column(Float)
    timeout_scheduled_for = Column(DateTime)
    cancelled = Column(Boolean, default=False)

    def get_launch_spec(self) -> dict:
        spec = super().get_launch_spec()
        spec["timeout"] = self.timeout
        spec["priority"] = self.priority
        return spec

    def __init__(
        self,
        function,
        arguments=None,
        trial=None,
        response=None,
        participant=None,
        node=None,
        network=None,
        asset=None,
        label=None,
        unique=False,
        timeout=None,
        priority="high",
    ):
        check_priority(priority)
        self.timeout = timeout
        super().__init__(
            function,
            arguments,
            trial=trial,
            response=response,
            participant=participant,
            node=node,
            network=network,
            asset=asset,
            label=label,
            unique=unique,
            priority=priority,
        )

    def log_time_started(self):
        """Record the start time and start the timeout, if any."""
        super().log_time_started()
        if self.timeout:
            self.timeout_scheduled_for = self.time_started + datetime.timedelta(
                seconds=self.timeout
            )

    @classmethod
    def get_redis_queue(cls, priority):
        """Return the RQ queue for jobs of the given priority."""
        return Queue(priority, connection=redis_conn)

    @classmethod
    def launch(cls, spec: dict):
        cls.get_redis_queue(spec["priority"]).enqueue_call(
            func=cls.call_function_with_logger,
            args=(),
            kwargs=dict(async_job_id=spec["id"]),
            timeout=spec["timeout"],
            job_id=_rq_job_id(spec["id"]),
        )

    @classmethod
    def _is_lost_before_start(cls, async_job_id):
        """Return whether RQ lost a job that has not started.

        A job is lost if RQ no longer has it, or if RQ failed, stopped or
        cancelled it. A job RQ reports as finished was run by a worker, and
        any other status, including ``created``, which RQ only sets while
        enqueueing, means RQ may still run it.

        Returns
        -------
        bool
            ``True`` if RQ has no record of the job or failed, stopped or
            cancelled it. ``False`` if RQ may still run it, or, with a
            warning, if Redis cannot be reached.
        """
        try:
            status = Job(_rq_job_id(async_job_id), connection=redis_conn).get_status()
        except InvalidJobOperation:
            return True
        except RedisError:
            logger.warning(
                "Could not check whether RQ still holds async job %s; not failing it.",
                async_job_id,
                exc_info=True,
            )
            return False
        return status in _RQ_LOST_STATUSES

    @classmethod
    def _is_overdue(cls, now):
        """Return a filter for pending jobs that timed out or never started."""
        start_deadline = now - datetime.timedelta(seconds=cls.max_queue_wait_sec)
        return and_(
            cls.pending,
            ~cls.failed,
            ~cls.finished,
            or_(
                cls.timeout_scheduled_for < now,
                and_(
                    cls.time_started == None,  # noqa: E711
                    cls.time_enqueued < start_deadline,
                ),
            ),
        )

    @classmethod
    def check_timeouts(cls):
        """Fail jobs that have timed out or were lost before starting.

        A job times out once it has run for longer than its ``timeout``. A job
        that has not started :attr:`max_queue_wait_sec` after being enqueued
        is failed if RQ lost it (see :meth:`_is_lost_before_start`);
        otherwise it keeps waiting. Failed jobs are no longer pending.
        """
        now = datetime.datetime.now()
        job_ids = [
            job_id
            for (job_id,) in db.session.query(cls.id).filter(cls._is_overdue(now))
        ]
        for job_id in job_ids:
            cls._fail_if_overdue(job_id, now)
            db.session.commit()

    @classmethod
    def _fail_if_overdue(cls, async_job_id, now):
        """Lock a job and fail it if it is still overdue at time ``now``.

        Re-checking under the lock skips a job that a worker started or
        finished since :meth:`check_timeouts` selected it.
        """
        job = (
            cls.query.filter(cls.id == async_job_id, cls._is_overdue(now))
            .with_for_update(of=AsyncJob)
            .populate_existing()
            .one_or_none()
        )
        if job is None:
            return
        if job.time_started is not None:
            job.fail("Async job timed out")
        elif cls._is_lost_before_start(job.id):
            job.fail(
                f"Async job did not start within {cls.max_queue_wait_sec} s "
                "of being enqueued and RQ no longer has it queued; "
                "it was probably lost"
            )
        else:
            return
        job.pending = False
        if job.participant_id is not None:
            from psynet.timeline_hold import _queue_timeline_hold_wake

            _queue_timeline_hold_wake(
                job.participant_id,
                reason="async_job_timed_out",
            )

    @property
    def redis_job_id(self):
        return _rq_job_id(self.id)

    @property
    def redis_job(self):
        return Job.fetch(self.redis_job_id, connection=redis_conn)

    def cancel(self):
        """Cancel the job.

        The caller's transaction saves the change; the queued RQ job is
        cancelled once that transaction commits, and not at all if it rolls
        back.
        """
        if self.cancelled:
            return
        self.cancelled = True
        self.pending = False
        self.fail("Cancelled async job")
        db.session.flush([self])
        _call_after_commit(partial(_cancel_rq_job, self.id))
        if self.participant_id is not None:
            from psynet.timeline_hold import _queue_timeline_hold_wake

            _queue_timeline_hold_wake(
                self.participant_id,
                reason="async_job_cancelled",
            )
