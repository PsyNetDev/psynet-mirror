import tempfile
import threading
import time

import pytest
from dallinger import db
from dallinger.db import redis_conn
from rq import Queue
from rq.exceptions import NoSuchJobError

import psynet.experiment  # noqa -- to ensure that all SQLAlchemy classes are registered
from psynet.db import forbid_commits
from psynet.process import LocalAsyncProcess, WorkerAsyncProcess
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
class TestProcesses:
    def test_process_that_fails(self):
        process = LocalAsyncProcess(failing_function)

        db.session.commit()
        time.sleep(0.5)
        db.session.commit()

        assert process.failed
        assert not process.finished
        assert not process.pending

    def test_async_process_participant(self, participant):
        assert len(participant.async_processes) == 0
        process = LocalAsyncProcess(do_nothing, participant=participant)
        db.session.commit()
        assert len(participant.async_processes) == 1

        # Give the process time to finish before we shut down the experiment.
        # If we don't, then we are likely to see a PytestUnhandledThreadExceptionWarning
        # from when the process tries to run but the app has already been shut down.
        time.sleep(0.5)
        db.session.commit()
        assert process.finished


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestProcesses2:
    def test_async_process_trial(self, trial, node, network, participant):
        # When a trial spawns an async process, this async process also is 'owned'
        # by the participant. The trial's node and network do not count as owners
        # of the process, however.
        db.session.commit()
        owners = [trial, participant]
        for o in owners:
            assert len(o.async_processes) == 0

        process = LocalAsyncProcess(sleep_for_1s, trial=trial)

        db.session.commit()

        for o in owners:
            assert len(o.async_processes) == 1

        time.sleep(1.5)

        db.session.commit()

        for o in owners:
            for p in o.async_processes:
                assert p.finished

        assert abs(process.time_taken - 1) < 0.5

    def test_invalid_function(self):
        def local_function():
            pass

        with pytest.raises(
            ValueError,
            match="You cannot serialize a lambda function or a function defined within another function.",
        ):
            LocalAsyncProcess(
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

        with pytest.raises(ValueError) as e:
            LocalAsyncProcess(
                a.instance_method,
                arguments={},
            )
            assert "You cannot pass an instance method to an AsyncProcess." in str(
                e.value
            )

    def test_local_process(self):
        message = "Hello!"

        with tempfile.NamedTemporaryFile(delete=False) as file:
            process = LocalAsyncProcess(
                self.sleep_then_write_to_file,
                dict(
                    duration=0.5,
                    file=file.name,
                    message=message,
                ),
            )

            db.session.commit()

            with open(file.name, "r") as file_reader:
                assert file_reader.readline() != message

            time.sleep(1.5)

            db.session.commit()
            assert process.finished

            with open(file.name, "r") as file_reader:
                assert file_reader.readline() == message

            assert abs(process.time_taken - 0.5) < 0.1

    @staticmethod
    def sleep_then_write_to_file(duration, file, message):
        time.sleep(duration)

        with open(file, "w") as file_writer:
            file_writer.write(message)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_processes_launch_only_on_their_own_sessions_commit(monkeypatch):
    """Another session's commit must not launch a process that is not committed yet."""
    launched = []
    monkeypatch.setattr(
        LocalAsyncProcess,
        "launch",
        classmethod(lambda cls, p: launched.append(p["id"])),
    )
    queued, release = threading.Event(), threading.Event()
    created = {}

    def create_then_commit():
        try:
            created["id"] = LocalAsyncProcess(do_nothing).id
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

    LocalAsyncProcess(do_nothing)
    db.session.rollback()
    db.session.commit()
    assert launched == [created["id"]]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_launch_queue_follows_savepoints_and_close(monkeypatch):
    """SAVEPOINTs and close() must not launch or lose processes early."""
    launched = []
    monkeypatch.setattr(
        LocalAsyncProcess,
        "launch",
        classmethod(lambda cls, p: launched.append(p["id"])),
    )

    outer = LocalAsyncProcess(do_nothing).id
    with db.session.begin_nested():
        released = LocalAsyncProcess(do_nothing).id
    assert launched == []
    nested = db.session.begin_nested()
    LocalAsyncProcess(do_nothing)
    nested.rollback()
    db.session.commit()
    assert launched == [outer, released]

    with db.session.begin_nested():
        LocalAsyncProcess(do_nothing)
    db.session.rollback()
    LocalAsyncProcess(do_nothing)
    db.session.close()
    db.session.commit()
    assert launched == [outer, released]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_cancel_cancels_the_queued_worker_job(monkeypatch):
    unworked_queue = Queue("psynet_test_unworked", connection=redis_conn)
    monkeypatch.setattr(WorkerAsyncProcess, "redis_queue", unworked_queue)

    process = WorkerAsyncProcess(do_nothing)
    db.session.commit()
    with forbid_commits("CodeBlock 'cancel_analysis'"):
        process.cancel()
        process.cancel()
    db.session.commit()

    assert process.redis_job.get_status() == "canceled"
    assert process.cancelled and not process.pending

    cancelled_before_launch = WorkerAsyncProcess(do_nothing)
    cancelled_before_launch.cancel()
    db.session.commit()
    with pytest.raises(NoSuchJobError):
        cancelled_before_launch.redis_job
