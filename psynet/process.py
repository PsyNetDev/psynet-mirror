import datetime
import threading
import time

import dallinger.db
from dallinger import db
from dallinger.db import redis_conn
from dallinger.utils import classproperty
from rq import Queue
from rq.job import Job
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    event,
)
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import deferred, relationship
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_exponential

from .data import SQLBase, SQLMixin, register_table
from .db import with_transaction
from .field import PythonDict, PythonObject
from .serialize import prepare_function_for_serialization
from .utils import get_logger

logger = get_logger()


@register_table
class AsyncProcess(SQLBase, SQLMixin):
    __tablename__ = "process"

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
    _unique_key = Column(PythonDict, unique=True)

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant",
        backref="async_processes",
        foreign_keys=[participant_id],
    )

    trial_maker_id = Column(String, index=True)

    network_id = Column(Integer, ForeignKey("network.id"), index=True)
    network = relationship("TrialNetwork", back_populates="async_processes")

    node_id = Column(Integer, ForeignKey("node.id"), index=True)
    node = relationship("TrialNode", back_populates="async_processes")

    trial_id = Column(Integer, ForeignKey("trial.id"), index=True)
    trial = relationship("psynet.trial.main.Trial", back_populates="async_processes")

    response_id = Column(Integer, ForeignKey("response.id"), index=True)
    response = relationship(
        "psynet.timeline.Response", back_populates="async_processes"
    )

    asset_id = Column(Integer, ForeignKey("asset.id"), index=True)
    asset = relationship("Asset", back_populates="async_processes")

    errors = relationship("ErrorRecord")

    launch_queue = []

    def add_to_launch_queue(self):
        self.time_enqueued = datetime.datetime.now()
        self.launch_queue.append(self.get_launch_spec())

    def get_launch_spec(self) -> dict:
        db.session.flush([self])
        return {
            "obj": self,
            "class": self.__class__,
            "id": self.id,
        }

    @classmethod
    def launch_all(cls):
        while cls.launch_queue:
            process = cls.launch_queue.pop(0)
            assert process["obj"].id is not None
            logger.info("Launching async process %s...", process["id"])
            process["class"].launch(process)

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
    ):
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

        db.session.add(self)
        self.add_to_launch_queue()

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
        These are the objects that will be failed if the process fails. Ultimately we might want to
        add more objects to this list, for example participants, assets, and networks,
        but currently we're not confident that PsyNet supports failing those objects in that kind of way.
        """
        candidates = [self.trial, self.node]
        return [lambda obj=obj: [obj] for obj in candidates if obj is not None]

    @classmethod
    def launch(cls, process: dict):
        raise NotImplementedError

    @classproperty
    def redis_queue(cls):
        return Queue("default", connection=redis_conn)

    @classmethod
    def call_function_with_logger(cls, process_id):
        cls.call_function(process_id)

    @classmethod
    @retry(
        retry=retry_if_exception_type(NoResultFound),
        wait=wait_exponential(multiplier=0.1, min=0.01),
        stop=stop_after_delay(4),
    )
    # The process gets launched when SQLAlchemy's after_commit event is triggered. This tells us when the COMMIT
    # has been issued to the database, but it does not guarantee that the commit has finished execution.
    # This is why we add some retry logic to ensure that the process is available in the database before continuing.
    def get_process(cls, process_id: int):
        return (
            AsyncProcess.query.filter_by(id=process_id)
            .with_for_update(of=AsyncProcess)
            .populate_existing()
            .one()
        )

    @classmethod
    @with_transaction
    def call_function(cls, process_id):
        """
        Calls the defining function of a given process
        """
        # cls.log(f"Calling function for process_id: {process_id}")
        print("\n")
        logger.info(f"Calling function for process_id {process_id}...")

        process = None

        try:
            from psynet.experiment import get_experiment

            experiment = get_experiment()

            process = cls.get_process(process_id)
            function = process.function

            arguments = cls.preprocess_args(process.arguments)

            timer = time.monotonic()
            process.time_started = datetime.datetime.now()
            if process.time_enqueued:
                process.queue_delay = (
                    process.time_started - process.time_enqueued
                ).total_seconds()
            db.session.commit()

            function(**arguments)

            process.time_finished = datetime.datetime.now()
            process.time_taken = time.monotonic() - timer
            process.pending = False
            process.finished = True

            from psynet.trial.main import Trial

            if "self" in arguments and isinstance(arguments["self"], Trial):
                arguments["self"].check_if_can_mark_as_finalized()

        except Exception as err:
            if not isinstance(err, experiment.HandledError):
                experiment.handle_error(err, process=process)

            if process:
                # We need to re-fetch the process because handle_error has done a rollback
                process = cls.get_process(process_id)
                process.pending = False
                process.fail(f"Exception in asynchronous process: {repr(err)}")

        finally:
            db.session.commit()

    @classmethod
    def preprocess_args(cls, arguments):
        """
        Preprocesses the arguments that are passed to the process's function.
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

    @classmethod
    def log(cls, msg):
        raise NotImplementedError

    @classmethod
    def log_to_stdout(cls, msg):
        print(msg)

    @classmethod
    def log_to_redis(cls, msg):
        cls.redis_queue.enqueue_call(
            func=logger.info, args=(), kwargs=dict(msg=msg), timeout=1e10, at_front=True
        )


@event.listens_for(db.session, "after_commit")
def receive_after_commit(session):
    AsyncProcess.launch_all()


class LocalAsyncProcess(AsyncProcess):
    @classmethod
    def launch(cls, process: dict):
        thr = threading.Thread(
            target=cls.thread_function, kwargs={"process_id": process["id"]}
        )
        thr.start()

    @classmethod
    def thread_function(cls, process_id):
        try:
            cls.call_function_with_logger(process_id)
        finally:
            db.session.commit()
            db.session.close()

    @classmethod
    def call_function_with_logger(cls, process_id):
        cls.call_function(process_id)

        # log = io.StringIO()
        # try:
        #     with contextlib.redirect_stdout(log):
        #         # yield
        #         cls.call_function(process_id)
        # finally:
        #     cls.log_to_redis(log.getvalue())

        # with cls.log_output():
        #     cls.call_function(process_id)

    # @classmethod
    # @contextlib.contextmanager
    # def log_output(cls):
    #     log = io.StringIO()
    #     try:
    #         with contextlib.redirect_stdout(log):
    #             yield
    #     finally:
    #         cls.log_to_redis(log.getvalue())

    # @classmethod
    # def log(cls, msg):
    #     cls.log_to_redis(msg)


class WorkerAsyncProcess(AsyncProcess):
    redis_job_id = Column(String)
    timeout = Column(Float)  # note -- currently only applies to non-local proceses
    timeout_scheduled_for = Column(DateTime)
    cancelled = Column(Boolean, default=False)

    def get_launch_spec(self) -> dict:
        spec = super().get_launch_spec()
        spec["timeout"] = self.timeout
        return spec

    def __init__(
        self,
        function,
        arguments=None,
        trial=None,
        participant=None,
        node=None,
        network=None,
        asset=None,
        label=None,
        unique=False,
        timeout=None,  # <-- new argument for this class
    ):
        self.timeout = timeout
        if timeout:
            self.timeout_scheduled_for = datetime.datetime.now() + datetime.timedelta(
                seconds=timeout
            )

        super().__init__(
            function,
            arguments,
            trial=trial,
            participant=participant,
            node=node,
            network=network,
            asset=asset,
            label=label,
            unique=unique,
        )

    @classmethod
    def launch(cls, process: dict):
        # Previously we took the id of the enqueue_call and saved that in Process.redis_job_id,
        # but this is not possible now that the Process object is not accessible.
        cls.redis_queue.enqueue_call(
            func=cls.call_function_with_logger,
            args=(),
            kwargs=dict(process_id=process["id"]),
            timeout=process["timeout"],
        )

    @classmethod
    def check_timeouts(cls):
        processes = cls.query.filter(
            cls.pending,
            ~cls.failed,
            cls.timeout != None,  # noqa -- this is special SQLAlchemy syntax
            cls.timeout_scheduled_for < datetime.datetime.now(),
        ).all()
        for p in processes:
            p.fail(
                "Asynchronous process timed out",
            )
            db.session.commit()

    @property
    def redis_job(self):
        return Job.fetch(self.redis_job_id, connection=redis_conn)

    def cancel(self):
        self.cancelled = True
        self.pending = False
        self.fail("Cancelled asynchronous process")
        self.redis_job.cancel()
        db.session.commit()

    # @classmethod
    # def log(cls, msg):
    #     cls.log_to_stdout(msg)
