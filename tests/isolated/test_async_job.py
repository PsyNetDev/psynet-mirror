import json
import tempfile
import threading
import time
import types
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner
from dallinger import db
from dallinger.db import redis_conn
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import JobStatus
from sqlalchemy.exc import IntegrityError

import psynet.experiment  # noqa -- to ensure that all SQLAlchemy classes are registered
from psynet.async_job import AsyncJob, LocalAsyncJob, WorkerAsyncJob
from psynet.command_line import psynet
from psynet.db import forbid_commits
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import AsyncCodeBlock
from psynet.trial.main import Trial
from psynet.utils import get_authenticated_session


def do_nothing():
    pass


def sleep_for_1s():
    time.sleep(1)


def failing_function():
    assert False, "This is an intentional error thrown for testing purposes."


def busy_for(seconds):
    end = time.thread_time() + seconds
    while time.thread_time() < end:
        pass


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
        assert job.cpu_time < 0.2

    def test_cpu_bound_job_records_cpu_time(self, launched_experiment):
        job = LocalAsyncJob(busy_for, {"seconds": 0.3}).enqueue()
        db.session.commit()
        for _ in range(50):
            time.sleep(0.1)
            db.session.commit()
            if job.finished:
                break

        assert job.finished
        assert 0.3 <= job.cpu_time <= job.time_taken

        base_url = launched_experiment.base_url
        response = get_authenticated_session(base_url).get(
            base_url + "/async_job_cpu_time"
        )
        response.raise_for_status()
        row = next(row for row in response.json() if row["label"] == "busy_for")
        assert row["runs_in"] == "web"
        assert row["mean_cpu"] >= 0.3

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
    monkeypatch.setattr(
        WorkerAsyncJob, "get_redis_queue", classmethod(lambda cls, p: unworked_queue)
    )

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
def test_timeout_counts_from_start_not_enqueue(monkeypatch):
    unworked_queue = Queue("psynet_test_unworked", connection=redis_conn)
    monkeypatch.setattr(
        WorkerAsyncJob, "get_redis_queue", classmethod(lambda cls, p: unworked_queue)
    )
    queued = WorkerAsyncJob(do_nothing, timeout=0.01).enqueue()
    stalled = WorkerAsyncJob(do_nothing, timeout=0.01).enqueue()
    stalled.log_time_started()
    backlog = WorkerAsyncJob(do_nothing).enqueue()
    lost = WorkerAsyncJob(do_nothing).enqueue()
    finished_in_rq = WorkerAsyncJob(do_nothing).enqueue()
    local_lost = LocalAsyncJob(do_nothing)
    db.session.add(local_lost)
    for job in [backlog, lost, finished_in_rq, local_lost]:
        job.time_enqueued = datetime.now() - timedelta(hours=2)
    db.session.commit()
    ids = dict(
        queued=queued.id,
        stalled=stalled.id,
        backlog=backlog.id,
        lost=lost.id,
        finished_in_rq=finished_in_rq.id,
        local_lost=local_lost.id,
    )
    lost.redis_job.delete()
    finished_in_rq.redis_job.set_status(JobStatus.FINISHED)
    time.sleep(0.05)
    AsyncJob.check_timeouts()
    for name in ["queued", "backlog", "finished_in_rq"]:
        job = AsyncJob.query.get(ids[name])
        assert job.pending and not job.failed
    stalled = AsyncJob.query.get(ids["stalled"])
    assert stalled.failed and not stalled.pending
    for name in ["lost", "local_lost"]:
        job = AsyncJob.query.get(ids[name])
        assert "probably lost" in job.failed_reason and not job.pending

    finished_in_rq = AsyncJob.query.get(ids["finished_in_rq"])
    finished_in_rq.pending, finished_in_rq.finished = False, True
    finished_in_rq.redis_job.delete()
    db.session.commit()
    AsyncJob._fail_if_overdue(finished_in_rq.id, datetime.now())
    db.session.commit()
    assert not AsyncJob.query.get(ids["finished_in_rq"]).failed

    queued_id, stalled_id, lost_id = ids["queued"], ids["stalled"], ids["lost"]
    WorkerAsyncJob.call_function(queued_id)
    queued = WorkerAsyncJob.query.get(queued_id)
    assert queued.finished and not queued.failed
    assert queued.timeout_scheduled_for > queued.time_started

    for job_id in [stalled_id, lost_id]:
        WorkerAsyncJob.call_function(job_id)
        job = WorkerAsyncJob.query.get(job_id)
        assert not job.finished and not job.pending


def time_out_own_job_then_raise():
    job = WorkerAsyncJob.query.filter_by(label="times_out_while_running").one()
    job.fail("Async job timed out")
    db.session.commit()
    raise RuntimeError("Interrupted by the timeout.")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_job_failing_after_the_clock_timed_it_out_keeps_the_timeout(monkeypatch):
    unworked_queue = Queue("psynet_test_unworked", connection=redis_conn)
    monkeypatch.setattr(
        WorkerAsyncJob, "get_redis_queue", classmethod(lambda cls, p: unworked_queue)
    )
    job = WorkerAsyncJob(
        time_out_own_job_then_raise, label="times_out_while_running"
    ).enqueue()
    db.session.commit()
    job_id = job.id

    WorkerAsyncJob.call_function(job_id)

    job = WorkerAsyncJob.query.get(job_id)
    assert job.failed_reason == "Async job timed out" and not job.pending


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_enqueue_enforces_unique():
    LocalAsyncJob(do_nothing, unique=True).enqueue()
    duplicate = LocalAsyncJob(do_nothing, unique=True)
    with pytest.raises(IntegrityError):
        duplicate.enqueue()
    db.session.rollback()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_worker_job_runs_on_the_queue_named_by_its_priority():
    default = WorkerAsyncJob(do_nothing).enqueue()
    low = WorkerAsyncJob(do_nothing, priority="low").enqueue()
    db.session.commit()

    assert default.priority == "high"
    assert default.redis_job.origin == "high"
    assert low.redis_job.origin == "low"


def test_invalid_priority_raises():
    with pytest.raises(ValueError, match="priority"):
        WorkerAsyncJob(do_nothing, priority="urgent")
    with pytest.raises(ValueError, match="priority"):
        AsyncCodeBlock(do_nothing, wait=False, priority="default")


def test_async_code_block_priority_follows_wait():
    assert AsyncCodeBlock(do_nothing, expected_wait=1).priority == "high"
    assert AsyncCodeBlock(do_nothing, wait=False).priority == "low"
    assert AsyncCodeBlock(do_nothing, wait=False, priority="high").priority == "high"


class _FeedbackTrial(Trial):
    def show_feedback(self, experiment, participant):
        pass


class _NoWaitFeedbackTrial(_FeedbackTrial):
    wait_for_feedback = False


class _GivesFeedbackTrial(Trial):
    def gives_feedback(self, experiment, participant):
        return True


class _LowFeedbackTrial(_FeedbackTrial):
    async_post_trial_priority = "low"


class _InvalidPriorityTrial(Trial):
    async_post_trial_priority = "urgent"


@pytest.mark.parametrize(
    "trial_class, check_performance, chain_type, expected",
    [
        (Trial, False, "across", "low"),
        (Trial, True, "across", "high"),
        (Trial, False, "within", "high"),
        (_FeedbackTrial, False, "across", "high"),
        (_GivesFeedbackTrial, False, "across", "high"),
        (_NoWaitFeedbackTrial, False, "across", "low"),
        (_LowFeedbackTrial, True, "within", "low"),
    ],
)
def test_async_post_trial_priority(
    trial_class, check_performance, chain_type, expected
):
    for flag in ["check_performance_at_end", "check_performance_every_trial"]:
        trial_maker = types.SimpleNamespace(
            check_performance_at_end=False,
            check_performance_every_trial=False,
            chain_type=chain_type,
        )
        setattr(trial_maker, flag, check_performance)
        assert trial_class._get_async_post_trial_priority(trial_maker) == expected


def test_invalid_async_post_trial_priority_raises():
    with pytest.raises(ValueError, match="priority"):
        _InvalidPriorityTrial._get_async_post_trial_priority(None)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_cpu_time_summary_says_where_jobs_run():
    from psynet.async_job import _get_cpu_time_summary

    for cls, cpu_time in [(LocalAsyncJob, 0.1), (WorkerAsyncJob, 0.3)]:
        job = cls(do_nothing, label="summary_test")
        job.finished, job.cpu_time, job.time_taken = True, cpu_time, 0.5
        db.session.add(job)

    summary = _get_cpu_time_summary()
    db.session.rollback()
    rows = [row for row in summary if row["label"] == "summary_test"]
    assert [(row["runs_in"], row["priority"], row["mean_cpu"]) for row in rows] == [
        ("web", None, 0.1),
        ("worker", "high", 0.3),
    ]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_pending_jobs_keep_the_app_awake(tmp_path):
    from psynet.async_job import _get_pending_job_summary
    from psynet.experiment import get_experiment

    experiment = get_experiment()
    AsyncJob.query.filter_by(pending=True).update({"pending": False})
    assert _get_pending_job_summary() == {
        "counts": {"high": 0, "low": 0, "local": 0},
        "total": 0,
        "oldest_age": None,
    }
    assert experiment.reason_to_stay_awake() is None

    WorkerAsyncJob(do_nothing).enqueue()
    WorkerAsyncJob(do_nothing, priority="low").enqueue()
    WorkerAsyncJob(do_nothing, priority="low").enqueue()
    LocalAsyncJob(do_nothing).enqueue()
    WorkerAsyncJob(do_nothing).enqueue().cancel()
    WorkerAsyncJob(do_nothing, timeout=1).enqueue().fail("Async job timed out")
    finished = WorkerAsyncJob(do_nothing).enqueue()
    finished.pending, finished.finished = False, True
    db.session.add(WorkerAsyncJob(do_nothing, label="never_enqueued"))
    db.session.flush()

    summary = _get_pending_job_summary()
    assert summary["counts"] == {"high": 1, "low": 2, "local": 1}
    assert summary["total"] == 4
    assert summary["oldest_age"] < 60
    assert experiment.reason_to_stay_awake() == (
        "4 async jobs are still pending "
        "(1 high priority, 2 low priority, 1 in the web process); "
        "the oldest was enqueued under a minute ago"
    )

    # Runs in this process, so it sees the uncommitted jobs.
    json_output = tmp_path / "status.json"
    result = CliRunner().invoke(
        psynet, ["async-job-status", "--json-output", str(json_output)]
    )
    db.session.rollback()
    assert result.exit_code == 0, result.output
    assert json.loads(json_output.read_text())["counts"] == summary["counts"]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_local_jobs_time_out_after_an_hour():
    job = LocalAsyncJob(do_nothing)
    assert job.timeout == AsyncJob.default_timeout == 3600
    job.time_enqueued = datetime.now()
    job.log_time_started()
    assert job.timeout_scheduled_for - job.time_started == timedelta(hours=1)
    job.timeout_scheduled_for = datetime.now() - timedelta(seconds=1)
    db.session.add(job)
    db.session.commit()
    job_id = job.id

    AsyncJob.check_timeouts()
    job = LocalAsyncJob.query.get(job_id)
    assert job.failed and not job.pending


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_check_timeouts_skips_a_job_that_cannot_be_failed(monkeypatch):
    jobs = [LocalAsyncJob(do_nothing), LocalAsyncJob(do_nothing)]
    for job in jobs:
        job.time_enqueued = datetime.now() - timedelta(hours=2)
        db.session.add(job)
    db.session.commit()
    broken_id, other_id = (job.id for job in jobs)

    original_fail = AsyncJob.fail

    def fail(self, reason=None):
        if self.id == broken_id:
            raise RuntimeError("the failure cascade raised")
        original_fail(self, reason)

    monkeypatch.setattr(AsyncJob, "fail", fail)
    AsyncJob.check_timeouts()

    assert AsyncJob.query.get(broken_id).pending
    assert AsyncJob.query.get(other_id).failed


def test_cpu_time_summary_flags_cpu_heavy_labels():
    from psynet.async_job import _format_cpu_time_summary

    summary = _format_cpu_time_summary(
        [
            {
                "runs_in": "worker",
                "label": "analyse",
                "priority": "high",
                "count": 3,
                "mean_cpu": 0.8,
                "max_cpu": 1.2,
                "mean_wall": 1.0,
            },
            {
                "runs_in": "web",
                "label": "upload",
                "priority": None,
                "count": 5,
                "mean_cpu": 0.01,
                "max_cpu": 0.02,
                "mean_wall": 0.5,
            },
        ]
    )
    rows = {line.split()[1]: line.split() for line in summary.splitlines()[2:]}
    assert rows["analyse"] == [
        "worker",
        "analyse",
        "high",
        "3",
        "0.800",
        "1.200",
        "1.000",
        "yes",
    ]
    assert rows["upload"][:3] == ["web", "upload", "-"]
    assert rows["upload"][-1] == "no"

    assert _format_cpu_time_summary([]) == "No async jobs finished."
