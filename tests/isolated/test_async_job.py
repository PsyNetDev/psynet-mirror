import tempfile
import threading
import time
import types

import pytest
from dallinger import db
from dallinger.db import redis_conn
from rq import Queue
from rq.exceptions import NoSuchJobError
from sqlalchemy.exc import IntegrityError

import psynet.experiment  # noqa -- to ensure that all SQLAlchemy classes are registered
from psynet.async_job import LocalAsyncJob, WorkerAsyncJob
from psynet.db import forbid_commits
from psynet.pytest_psynet import path_to_test_experiment


def do_nothing():
    pass


def sleep_for_1s():
    time.sleep(1)


def failing_function():
    assert False, "This is an intentional error thrown for testing purposes."


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestAsyncJobs:
    def test_job_that_fails(self):
        job = LocalAsyncJob(failing_function).enqueue()

        db.session.commit()
        time.sleep(0.5)
        db.session.commit()

        assert job.failed
        assert not job.finished
        assert not job.pending

    def test_async_job_participant(self, participant):
        assert len(participant.async_jobs) == 0
        job = LocalAsyncJob(do_nothing, participant=participant).enqueue()
        db.session.commit()
        assert len(participant.async_jobs) == 1

        # Give the job time to finish before we shut down the experiment.
        # If we don't, then we are likely to see a PytestUnhandledThreadExceptionWarning
        # from when the job tries to run but the app has already been shut down.
        time.sleep(0.5)
        db.session.commit()
        assert job.finished


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestAsyncJobs2:
    def test_async_job_trial(self, trial, node, network, participant):
        # When a trial spawns an async job, this async job also is 'owned'
        # by the participant. The trial's node and network do not count as owners
        # of the job, however.
        db.session.commit()
        owners = [trial, participant]
        for o in owners:
            assert len(o.async_jobs) == 0

        job = LocalAsyncJob(sleep_for_1s, trial=trial).enqueue()

        db.session.commit()

        for o in owners:
            assert len(o.async_jobs) == 1

        time.sleep(1.5)

        db.session.commit()

        for o in owners:
            for p in o.async_jobs:
                assert p.finished

        assert abs(job.time_taken - 1) < 0.5

    def test_invalid_function(self):
        def local_function():
            pass

        with pytest.raises(
            ValueError,
            match="You cannot serialize a lambda function or a function defined within another function.",
        ):
            LocalAsyncJob(
                local_function,
                arguments={},
            )

        class A:
            def instance_method(self):
                pass

            @classmethod
            def class_method(cls):
                pass

        a = A()

        with pytest.raises(ValueError, match="You cannot serialize a lambda function"):
            LocalAsyncJob(
                a.instance_method,
                arguments={},
            )

    def test_local_job(self):
        message = "Hello!"

        with tempfile.NamedTemporaryFile(delete=False) as file:
            job = LocalAsyncJob(
                self.sleep_then_write_to_file,
                dict(
                    duration=0.5,
                    file=file.name,
                    message=message,
                ),
            ).enqueue()

            db.session.commit()

            with open(file.name, "r") as file_reader:
                assert file_reader.readline() != message

            time.sleep(1.5)

            db.session.commit()
            assert job.finished

            with open(file.name, "r") as file_reader:
                assert file_reader.readline() == message

            assert abs(job.time_taken - 0.5) < 0.1

    @staticmethod
    def sleep_then_write_to_file(duration, file, message):
        time.sleep(duration)

        with open(file, "w") as file_writer:
            file_writer.write(message)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_jobs_launch_only_on_their_own_sessions_commit(monkeypatch):
    """Another session's commit must not launch a job that is not committed yet."""
    launched = []
    monkeypatch.setattr(
        LocalAsyncJob,
        "launch",
        classmethod(lambda cls, p: launched.append(p["id"])),
    )
    queued, release = threading.Event(), threading.Event()
    created = {}

    def create_then_commit():
        try:
            created["id"] = LocalAsyncJob(do_nothing).enqueue().id
            queued.set()
            release.wait(timeout=10)
            db.session.commit()
        finally:
            db.session.remove()

    worker = threading.Thread(target=create_then_commit)
    worker.start()
    assert queued.wait(timeout=10)
    db.session.commit()
    assert launched == []

    release.set()
    worker.join(timeout=10)
    assert launched == [created["id"]]

    LocalAsyncJob(do_nothing).enqueue()
    db.session.rollback()
    db.session.commit()
    assert launched == [created["id"]]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_launch_queue_follows_savepoints_and_close(monkeypatch):
    """SAVEPOINTs and close() must not launch or lose jobs early."""
    launched = []
    monkeypatch.setattr(
        LocalAsyncJob,
        "launch",
        classmethod(lambda cls, p: launched.append(p["id"])),
    )

    outer = LocalAsyncJob(do_nothing).enqueue().id
    with db.session.begin_nested():
        released = LocalAsyncJob(do_nothing).enqueue().id
    assert launched == []
    nested = db.session.begin_nested()
    LocalAsyncJob(do_nothing).enqueue()
    nested.rollback()
    db.session.commit()
    assert launched == [outer, released]

    with db.session.begin_nested():
        LocalAsyncJob(do_nothing).enqueue()
    db.session.rollback()
    LocalAsyncJob(do_nothing).enqueue()
    db.session.close()
    db.session.commit()
    assert launched == [outer, released]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_failed_launch_alerts_and_later_launches_still_run(monkeypatch):
    launched = []

    def launch(cls, job):
        if not launched:
            launched.append(None)
            raise ConnectionError("Redis is down")
        launched.append(job["id"])

    alerts = []
    monkeypatch.setattr(LocalAsyncJob, "launch", classmethod(launch))
    monkeypatch.setattr("psynet.async_job._send_alert", alerts.append)

    failed = LocalAsyncJob(do_nothing).enqueue().id
    later = LocalAsyncJob(do_nothing).enqueue().id
    db.session.commit()

    assert launched == [None, later]
    assert len(alerts) == 1 and f"Async job {failed}" in alerts[0]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_cancel_cancels_the_queued_worker_job(monkeypatch):
    unworked_queue = Queue("psynet_test_unworked", connection=redis_conn)
    monkeypatch.setattr(WorkerAsyncJob, "redis_queue", unworked_queue)

    job = WorkerAsyncJob(do_nothing).enqueue()
    db.session.commit()
    with forbid_commits("CodeBlock 'cancel_analysis'"):
        job.cancel()
        job.cancel()
    db.session.commit()

    assert job.redis_job.get_status() == "canceled"
    assert job.cancelled and not job.pending
    async_job_id = job.id
    WorkerAsyncJob.call_function(async_job_id)
    assert not WorkerAsyncJob.query.get(async_job_id).finished

    cancelled_before_launch = WorkerAsyncJob(do_nothing).enqueue()
    cancelled_before_launch.cancel()
    db.session.commit()
    with pytest.raises(NoSuchJobError):
        cancelled_before_launch.redis_job

    cancel_rolled_back = WorkerAsyncJob(do_nothing).enqueue()
    savepoint = db.session.begin_nested()
    cancel_rolled_back.cancel()
    savepoint.rollback()
    db.session.commit()
    assert cancel_rolled_back.redis_job.get_status() == "queued"

    cancel_rolled_back.cancel()
    db.session.rollback()
    assert cancel_rolled_back.redis_job.get_status() == "queued"
    assert cancel_rolled_back.pending and not cancel_rolled_back.cancelled


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_only_enqueued_jobs_launch(monkeypatch, caplog):
    launched = []
    monkeypatch.setattr(
        LocalAsyncJob,
        "launch",
        classmethod(lambda cls, p: launched.append(p["id"])),
    )

    enqueued = LocalAsyncJob(do_nothing).enqueue()
    with pytest.raises(RuntimeError, match="already been enqueued"):
        enqueued.enqueue()
    forgotten = LocalAsyncJob(do_nothing, label="forgotten")
    db.session.add(forgotten)
    with caplog.at_level("WARNING", logger="psynet"):
        db.session.commit()

    assert launched == [enqueued.id]
    assert (
        f"Async job {forgotten.id} (label 'forgotten') was created but never enqueued"
        in caplog.text
    )
    assert "label 'do_nothing'" not in caplog.text


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_deprecated_process_names_still_work(monkeypatch, participant):
    import psynet.process
    from psynet.async_job import AsyncJob

    launched = []
    monkeypatch.setattr(
        LocalAsyncJob,
        "launch",
        classmethod(lambda cls, p: launched.append(p["id"])),
    )

    with pytest.warns(DeprecationWarning, match="renamed to psynet.async_job.AsyncJob"):
        assert psynet.process.AsyncProcess is AsyncJob
    with pytest.warns(DeprecationWarning, match="LocalAsyncJob"):
        job = psynet.process.LocalAsyncProcess(do_nothing, participant=participant)
    db.session.commit()
    assert launched == [job.id]
    with pytest.warns(DeprecationWarning, match="renamed to async_jobs"):
        assert participant.async_processes == [job]
    with pytest.warns(DeprecationWarning, match="LocalAsyncJob"):
        assert isinstance(job, psynet.process.LocalAsyncProcess)
    with pytest.warns(DeprecationWarning, match="WorkerAsyncJob"):
        assert not isinstance(job, psynet.process.WorkerAsyncProcess)
    with pytest.warns(DeprecationWarning, match="LocalAsyncJob"):
        assert psynet.process.LocalAsyncProcess.query.all() == [job]
    with pytest.warns(DeprecationWarning, match="renamed to get_async_job"):
        assert AsyncJob.get_process(job.id) is job
    with pytest.warns(DeprecationWarning, match="LocalAsyncJob"):
        assert types.resolve_bases((psynet.process.LocalAsyncProcess,)) == (
            LocalAsyncJob,
        )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_enqueue_starts_timeout_and_enforces_unique():
    job = WorkerAsyncJob(do_nothing, timeout=30)
    assert job.timeout_scheduled_for is None
    job.enqueue()
    assert (job.timeout_scheduled_for - job.time_enqueued).total_seconds() == 30

    LocalAsyncJob(do_nothing, unique=True).enqueue()
    duplicate = LocalAsyncJob(do_nothing, unique=True)
    with pytest.raises(IntegrityError):
        duplicate.enqueue()
    db.session.rollback()
