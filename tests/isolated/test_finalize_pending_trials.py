import uuid

import pytest
from dallinger import db

from psynet.error import ErrorRecord
from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.trial.chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker
from psynet.trial.main import Trial


def _reserve_trial_recording(trial, directory, *, required=True):
    """Reserve a camera clip for an accepted trial response."""
    from psynet.asset import LocalStorage
    from psynet.media_upload import _reserve_recording
    from psynet.timeline import Response

    label = "video"
    response = Response(
        participant=trial.participant, label=label, page_type="ModularPage"
    )
    response.successful_validation = True
    return _reserve_recording(
        response=response,
        parent=trial,
        page_uuid=label,
        source="camera",
        local_key="video",
        storage=LocalStorage(str(directory)),
        role="answer",
        required_for_trial=required,
        upload_timeout=60,
    )


class FinalizeBackstopTrial(ChainTrial):
    time_estimate = 1

    def make_definition(self, experiment, participant):
        return self.node.definition

    def on_finalized(self):
        # Skip the chain growth fast-path; this test only covers finalization.
        Trial.on_finalized(self)


class FinalizeBackstopNode(ChainNode):
    def create_initial_seed(self, experiment, participant):
        return {"x": 0}

    def summarize_trials(self, trials, experiment, participant):
        return {"x": trials[0].answer}

    def create_definition_from_seed(self, seed, experiment, participant):
        return seed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("still_waiting", [False, True])
def test_while_loop_budget_is_fixed_and_a_cleared_condition_exits_normally(
    db_session, participant, monkeypatch, still_waiting
):
    """A callable ``max_loop_time`` is evaluated once, on entering the loop.

    Past that budget, ``while_loop`` times out only if its condition still
    holds; a condition that cleared after the deadline exits normally.
    """
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    import psynet.timeline as timeline_module
    from psynet.page import InfoPage, WaitPage
    from psynet.timeline import Timeline, while_loop

    now = datetime.now()
    monkeypatch.setattr(timeline_module, "datetime", SimpleNamespace(now=lambda: now))
    calls = []
    pending = True

    def budget(participant):
        calls.append(participant.id)
        return 60 if len(calls) == 1 else 1

    timeline = Timeline(
        while_loop(
            "bounded_wait",
            lambda: pending,
            WaitPage(wait_time=1),
            expected_repetitions=0,
            max_loop_time=budget,
            fail_on_timeout=False,
            on_timeout=lambda participant: participant.var.set("timed_out", True),
        ),
        InfoPage("Continue", time_estimate=0),
    )
    exp = get_experiment()
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    now += timedelta(seconds=30)
    timeline.advance_page(exp, participant)
    assert isinstance(timeline.get_current_elt(exp, participant), WaitPage)
    assert calls == [participant.id]
    now += timedelta(seconds=35)
    pending = still_waiting
    timeline.advance_page(exp, participant)
    assert timeline.get_current_elt(exp, participant).content == "Continue"
    assert bool(participant.var.get("timed_out", False)) is still_waiting
    assert calls == [participant.id]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("expiry_source", ["clock", "poll", "late_poll"])
@pytest.mark.parametrize("upload_state", ["pending", "processing"])
def test_feedback_honors_recording_deadline_and_releases_a_resumed_tab(
    db_session, participant, monkeypatch, tmp_path, expiry_source, upload_state
):
    from datetime import datetime, timedelta

    from timeline_hold_helpers import _process_response

    import psynet.media_upload as uploads
    from psynet.page import InfoPage
    from psynet.timeline import Timeline
    from psynet.timeline_hold import _ConditionHoldPage

    now = datetime.now()
    monkeypatch.setattr(uploads, "_utcnow", lambda: now)
    monkeypatch.setattr("psynet.timeline_hold.timenow", lambda: now)
    exp = get_experiment()
    network = _create_network(_chain_trial_maker(), exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)
    participant.current_trial = trial
    asset, _ = _reserve_trial_recording(trial, tmp_path)
    # The ordinary 20 s, the 60 s upload allowance, then the processing bound.
    assert uploads._recording_wait_timeout(participant.id, trial_id=trial.id) == (
        20 + 60 + uploads._PROCESSING_BOUND
    )
    assert uploads._recording_wait_timeout(participant.id + 100) == 20
    assert (
        uploads._recording_wait_timeout(participant.id, trial_id=trial.id + 100) == 20
    )
    assert uploads._recording_wait_timeout(participant.id, None) is None
    # Once bytes arrive, the processing deadline replaces the upload allowance.
    asset.upload_status = "received"
    asset.upload_processing_deadline = now + timedelta(seconds=10)
    assert uploads._recording_wait_timeout(participant.id, trial_id=trial.id) == 30
    asset.upload_status = upload_state
    asset.upload_processing_deadline = (
        now + timedelta(seconds=60) if upload_state == "processing" else None
    )

    def show_feedback(self, experiment, participant):
        raise AssertionError("Missing media must not reach feedback")

    monkeypatch.setattr(FinalizeBackstopTrial, "show_feedback", show_feedback)
    timeline = Timeline(
        FinalizeBackstopTrial._construct_feedback_logic(None),
        InfoPage("Continue", time_estimate=0),
    )
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    now += timedelta(seconds=30)
    _process_response(
        exp, participant, participant.page_uuid, timeline_hold_resume=True
    )
    assert isinstance(timeline.get_current_elt(exp, participant), _ConditionHoldPage)
    assert not participant.failed
    participant_id, trial_id = participant.id, trial.id
    deadline = asset.upload_deadline
    db.session.commit()
    now += timedelta(seconds=40)
    if expiry_source == "clock":
        uploads._expire_recordings()
        participant = db.session.get(Participant, participant_id)
        now += timedelta(seconds=1000)
    elif expiry_source == "late_poll":
        now += timedelta(seconds=1000)
    else:
        # Read-only readiness detects the elapsed deadline but must not fail
        # anything before the request acquires its participant lock.
        hold = timeline.get_current_elt(exp, participant)
        assert hold.is_ready_to_resume(exp, participant)
        assert not trial.failed
        assert asset.upload_status == upload_state
    _process_response(
        exp, participant, participant.page_uuid, timeline_hold_resume=True
    )
    assert participant.current_trial.failed_reason == (
        "recording_upload_timeout"
        if upload_state == "pending"
        else "recording_processing_timeout"
    )
    assert uploads._recording_wait_timeout(participant_id, trial_id=trial_id) == 20
    assert timeline.get_current_elt(exp, participant).content == "Continue"
    assert not participant.failed
    assert participant.current_trial.assets["video"].upload_deadline == deadline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_trial_selection_refreshes_before_timing_out_a_resumed_tab(
    db_session, participant, monkeypatch
):
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    import psynet.timeline as timeline_module
    from psynet.page import InfoPage, WaitPage
    from psynet.timeline import Timeline

    now = datetime.now()
    monkeypatch.setattr(timeline_module, "datetime", SimpleNamespace(now=lambda: now))
    maker = _chain_trial_maker()
    pending = True

    def prepare(experiment, participant):
        participant.trial_status = "wait" if pending else "exit"

    monkeypatch.setattr(maker, "_try_to_prepare_trial_solo", prepare)
    timeline = Timeline(maker._wait_for_trial(), InfoPage("Continue", time_estimate=0))
    exp = get_experiment()
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    assert isinstance(timeline.get_current_elt(exp, participant), WaitPage)
    pending = False
    now += timedelta(seconds=1000)
    timeline.advance_page(exp, participant)
    assert timeline.get_current_elt(exp, participant).content == "Continue"
    assert not participant.failed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_failed_trial_does_not_run_late_analysis(db_session, participant, monkeypatch):
    exp = get_experiment()
    network = _create_network(_chain_trial_maker(), exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)
    calls = []
    monkeypatch.setattr(
        FinalizeBackstopTrial, "async_post_trial", lambda self: calls.append(self.id)
    )
    trial.fail(reason="recording_upload_timeout")
    trial.check_if_can_run_async_post_trial()
    assert not trial.async_post_trial_requested
    trial.call_async_post_trial()
    assert calls == []
    assert not trial.async_post_trial_complete
    assert not trial.finalized


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("reason", ["recording_upload_timeout", "analysis"])
def test_recording_failure_exits_feedback_wait(
    db_session, participant, monkeypatch, reason
):
    from timeline_hold_helpers import _process_response

    from psynet.asset import FileAsset
    from psynet.page import InfoPage
    from psynet.timeline import Timeline
    from psynet.timeline_hold import _ConditionHoldPage

    exp = get_experiment()
    network = _create_network(_chain_trial_maker(), exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)
    asset = FileAsset(
        local_key="pending",
        input_path=None,
        is_folder=False,
        extension=".webm",
        parent=trial,
    )
    db.session.add(asset)
    trial.assets["pending"] = asset
    participant.current_trial = trial
    feedback = []

    def show_feedback(self, experiment, participant):
        feedback.append(self.id)
        return InfoPage("Feedback", time_estimate=0)

    monkeypatch.setattr(FinalizeBackstopTrial, "show_feedback", show_feedback)
    timeline = Timeline(
        FinalizeBackstopTrial._construct_feedback_logic(None),
        InfoPage("Continue", time_estimate=0),
    )
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    assert isinstance(timeline.get_current_elt(exp, participant), _ConditionHoldPage)
    trial.fail(reason=reason)
    if reason == "analysis":
        asset.deposited = True
    _process_response(
        exp, participant, participant.page_uuid, timeline_hold_resume=True
    )
    if reason == "analysis":
        assert timeline.get_current_elt(exp, participant).content == "Feedback"
        assert feedback
        assert trial.ready_for_feedback
    else:
        assert timeline.get_current_elt(exp, participant).content == "Continue"
        assert feedback == []
        assert not trial.ready_for_feedback
        assert not asset.deposited
    assert not participant.failed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("threshold, passed", [(0, True), (1, False)])
def test_failed_recording_releases_end_wait_without_bypassing_performance_check(
    db_session, participant, monkeypatch, threshold, passed
):
    from timeline_hold_helpers import _process_response

    from psynet.asset import FileAsset
    from psynet.page import InfoPage
    from psynet.timeline import Timeline
    from psynet.timeline_hold import _ConditionHoldPage

    exp = get_experiment()
    maker = _chain_trial_maker()
    maker.performance_check_type = "performance"
    maker.performance_threshold = threshold
    maker.give_end_feedback_passed = False
    maker.end_performance_check_waits = True
    participant.module_state = maker.state_class(maker, participant)
    network = _create_network(maker, exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)
    asset = FileAsset(
        local_key="pending",
        input_path=None,
        is_folder=False,
        extension=".webm",
        parent=trial,
    )
    db.session.add(asset)
    trial.assets["pending"] = asset
    # Use an author-supplied failure page to observe the normal configured branch.
    monkeypatch.setattr(
        maker, "check_fail_logic", lambda: InfoPage("Failed check", time_estimate=0)
    )
    timeline = Timeline(
        maker._check_performance_logic("end"), InfoPage("Continue", time_estimate=0)
    )
    monkeypatch.setattr(exp, "timeline", timeline)
    participant.elt_id = ["main", -1]
    timeline.advance_page(exp, participant)
    assert isinstance(timeline.get_current_elt(exp, participant), _ConditionHoldPage)
    trial.fail(reason="recording_upload_timeout")
    _process_response(
        exp, participant, participant.page_uuid, timeline_hold_resume=True
    )
    assert participant.module_state.performance_check["passed"] is passed
    assert timeline.get_current_elt(exp, participant).content == (
        "Continue" if passed else "Failed check"
    )
    assert not asset.deposited


@pytest.fixture
def participant(db_session):
    exp = get_experiment()
    participant = Participant(
        experiment=exp,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    db.session.flush()
    return participant


def _chain_trial_maker():
    return ChainTrialMaker(
        id_="finalize_backstop",
        node_class=FinalizeBackstopNode,
        trial_class=FinalizeBackstopTrial,
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        chains_per_experiment=1,
        max_nodes_per_chain=2,
        trials_per_node=1,
        recruit_mode="n_trials",
    )


def _create_network(trial_maker, experiment):
    start_node = trial_maker.node_class(definition={"x": 0})
    network = ChainNetwork(
        trial_maker_id=trial_maker.id,
        start_node=start_node,
        experiment=experiment,
        chain_type=trial_maker.chain_type,
        trials_per_node=trial_maker.trials_per_node,
        target_n_nodes=trial_maker.max_nodes_per_chain,
    )
    db.session.add(network)
    db.session.flush()
    return network


def _add_complete_unfinalized_trial(node, participant, **kwargs):
    trial = FinalizeBackstopTrial(
        experiment=get_experiment(),
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    trial.finalized = False
    for key, value in kwargs.items():
        setattr(trial, key, value)
    db.session.add(trial)
    db.session.flush()
    return trial


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_recovers_missed_callback(db_session, participant):
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)
    db.session.commit()

    assert trial.finalized is False
    finalized_count = Trial.finalize_pending_trials()
    db.session.commit()

    assert finalized_count == 1
    assert trial.finalized is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_skips_blocked_trials(db_session, participant):
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(
        network.head,
        participant,
        async_post_trial_requested=True,
        async_post_trial_complete=False,
    )
    db.session.commit()

    assert Trial.get_trials_ready_to_finalize() == []
    assert Trial.finalize_pending_trials() == 0
    assert trial.finalized is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_skips_asset_deposit_pending(
    db_session, participant, tmp_path
):
    from psynet.asset import FileAsset

    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(network.head, participant)

    asset_path = tmp_path / "pending.txt"
    asset_path.write_text("pending")
    asset = FileAsset(
        local_key="pending",
        input_path=str(asset_path),
        parent=trial,
    )
    db.session.add(asset)
    trial.assets["pending"] = asset
    db.session.commit()

    assert asset.trial_id == trial.id
    assert asset.deposited is False
    assert trial.asset_deposit_pending is True
    assert Trial.get_trials_ready_to_finalize() == []
    assert Trial.finalize_pending_trials() == 0
    assert trial.finalized is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_failed_async_blocks_finalization_even_if_not_pending(db_session, participant):
    """Failed async is not 'pending' but must still block finalize."""
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = _add_complete_unfinalized_trial(
        network.head,
        participant,
        async_post_trial_requested=True,
        async_post_trial_complete=False,
        async_post_trial_failed=True,
    )
    db.session.commit()

    assert trial.async_post_trial_pending is False
    assert trial.async_post_trial_blocks_finalization is True
    assert Trial.get_trials_ready_to_finalize() == []
    trial.check_if_can_mark_as_finalized()
    assert trial.finalized is False


class FailingAsyncTrial(FinalizeBackstopTrial):
    run_async_post_trial = True

    def async_post_trial(self):
        raise RuntimeError("intentional async_post_trial failure")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_call_async_post_trial_failure_fails_trial(db_session, participant):
    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    network = _create_network(trial_maker, exp)
    trial = FailingAsyncTrial(
        experiment=exp,
        node=network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    trial.finalized = False
    trial.async_post_trial_requested = True
    db.session.add(trial)
    db.session.commit()

    with pytest.raises(RuntimeError, match="intentional async_post_trial failure"):
        trial.call_async_post_trial()

    db.session.refresh(trial)
    assert trial.async_post_trial_failed is True
    assert trial.failed is True
    assert "async_post_trial_failed" in (trial.failed_reason or "")
    assert trial.finalized is False
    assert Trial.get_trials_ready_to_finalize() == []


class ConcurrentResponseAsyncTrial(FinalizeBackstopTrial):
    run_async_post_trial = True

    def async_post_trial(self):
        # Simulate the participant's response committing from another process
        # while the worker still holds a cached ``complete=False``.
        table = Trial.__table__
        with db.engine.begin() as connection:
            connection.execute(
                table.update().where(table.c.id == self.id).values(complete=True)
            )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_async_post_trial_finalizes_trial_completed_concurrently(
    db_session, participant, monkeypatch, caplog
):
    from psynet.async_job import WorkerAsyncJob

    exp = get_experiment()
    network = _create_network(_chain_trial_maker(), exp)
    trial = ConcurrentResponseAsyncTrial(
        experiment=exp,
        node=network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.async_post_trial_requested = True
    db.session.add(trial)
    db.session.flush()
    # Saved without enqueue() so that the test runs the job itself.
    job = WorkerAsyncJob(trial.call_async_post_trial, trial=trial)
    db.session.add(job)
    db.session.flush()
    async_job_id, trial_id = job.id, trial.id
    with caplog.at_level("WARNING", logger="psynet"):
        db.session.commit()
    assert "never enqueued" in caplog.text

    WorkerAsyncJob.call_function(async_job_id)

    trial = db.session.get(Trial, trial_id, populate_existing=True)
    assert trial.complete is True
    assert trial.async_post_trial_complete is True
    assert trial.finalized is True


class CommittingFinalizeTrial(FinalizeBackstopTrial):
    def on_finalized(self):
        db.session.commit()


class CommittingFinalizeAsyncTrial(CommittingFinalizeTrial):
    run_async_post_trial = True

    def async_post_trial(self):
        pass


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.parametrize("path", ["async_post_trial", "asset_deposit"])
@pytest.mark.usefixtures("in_experiment_directory")
def test_on_finalized_commit_after_a_worker_is_forbidden_and_fails_the_trial(
    db_session, participant, monkeypatch, tmp_path, path
):
    """Workers leave finalization to the post-commit re-check, whose failure
    leaves the trial to the backstop, which fails it."""
    from psynet.asset import FileAsset
    from psynet.async_job import LocalAsyncJob, WorkerAsyncJob

    exp = get_experiment()
    monkeypatch.setattr(
        type(exp),
        "log_to_notifier",
        classmethod(lambda cls, *args, **kwargs: None),
    )
    network = _create_network(_chain_trial_maker(), exp)
    trial_class = (
        CommittingFinalizeAsyncTrial
        if path == "async_post_trial"
        else CommittingFinalizeTrial
    )
    trial = trial_class(
        experiment=exp,
        node=network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    db.session.add(trial)
    db.session.flush()
    if path == "async_post_trial":
        trial.async_post_trial_requested = True
        job = WorkerAsyncJob(trial.call_async_post_trial, trial=trial)
    else:
        asset_path = tmp_path / "recording.txt"
        asset_path.write_text("recording")
        asset = FileAsset(
            local_key="recording", input_path=str(asset_path), parent=trial
        )
        db.session.add(asset)
        trial.assets["recording"] = asset
        asset.deposited = True
        job = LocalAsyncJob(asset.after_deposit, asset=asset)
    db.session.add(job)
    db.session.flush()
    async_job_id, trial_id = job.id, trial.id
    db.session.commit()

    type(job).call_function(async_job_id)

    trial = db.session.get(Trial, trial_id, populate_existing=True)
    assert (trial.finalized, trial.failed) == (False, False)

    Trial.finalize_pending_trials()
    db.session.commit()

    trial = db.session.get(Trial, trial_id, populate_existing=True)
    assert trial.finalized is False
    assert trial.failed is True
    assert "on_finalized" in ErrorRecord.query.one().message


class ExplodingFinalizeTrial(FinalizeBackstopTrial):
    def on_finalized(self):
        raise RuntimeError("intentional finalize backstop failure")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_isolates_per_trial_errors(
    db_session, participant, monkeypatch
):
    # Error notifications need a dashboard URL; skip notifier I/O.
    monkeypatch.setattr(
        type(get_experiment()),
        "log_to_notifier",
        classmethod(lambda cls, *args, **kwargs: None),
    )

    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    good_network = _create_network(trial_maker, exp)
    bad_network = _create_network(trial_maker, exp)

    good_trial = _add_complete_unfinalized_trial(good_network.head, participant)
    bad_trial = ExplodingFinalizeTrial(
        experiment=exp,
        node=bad_network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    bad_trial.answer = 1
    bad_trial.complete = True
    bad_trial.finalized = False
    db.session.add(bad_trial)
    db.session.commit()

    assert Trial.finalize_pending_trials() == 1
    db.session.commit()

    db.session.refresh(good_trial)
    db.session.refresh(bad_trial)
    assert bad_trial.failed is True
    assert "finalize_backstop_error" in (bad_trial.failed_reason or "")
    assert good_trial.finalized is True
    assert [record.trial_id for record in ErrorRecord.query.all()] == [bad_trial.id]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_pending_trials_fails_every_bad_trial(
    db_session, participant, monkeypatch
):
    """Two bad trials in one poll must both stay failed (not O(k) retries)."""
    monkeypatch.setattr(
        type(get_experiment()),
        "log_to_notifier",
        classmethod(lambda cls, *args, **kwargs: None),
    )

    exp = get_experiment()
    trial_maker = _chain_trial_maker()
    first_network = _create_network(trial_maker, exp)
    second_network = _create_network(trial_maker, exp)

    first_bad = ExplodingFinalizeTrial(
        experiment=exp,
        node=first_network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    first_bad.answer = 1
    first_bad.complete = True
    first_bad.finalized = False
    second_bad = ExplodingFinalizeTrial(
        experiment=exp,
        node=second_network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    second_bad.answer = 1
    second_bad.complete = True
    second_bad.finalized = False
    db.session.add_all([first_bad, second_bad])
    db.session.commit()

    Trial.finalize_pending_trials()
    db.session.commit()

    db.session.refresh(first_bad)
    db.session.refresh(second_bad)
    assert first_bad.failed is True
    assert second_bad.failed is True
    assert Trial.get_trials_ready_to_finalize() == []
    assert Trial.finalize_pending_trials() == 0


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_recheck_finalization_leaves_failing_trial_to_backstop(
    db_session, participant, monkeypatch
):
    from psynet.async_job import WorkerAsyncJob

    exp = get_experiment()
    network = _create_network(_chain_trial_maker(), exp)
    trial = ExplodingFinalizeTrial(
        experiment=exp,
        node=network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    trial.finalized = False
    db.session.add(trial)
    db.session.flush()
    job = WorkerAsyncJob(_do_nothing, trial=trial)
    db.session.add(job)
    db.session.flush()
    async_job_id, trial_id = job.id, trial.id
    db.session.commit()

    WorkerAsyncJob.call_function(async_job_id)

    assert [t.id for t in Trial.get_trials_ready_to_finalize()] == [trial_id]
    assert not Trial.query.get(trial_id).ready_for_feedback

    wakes = []
    monkeypatch.setattr(
        "psynet.timeline_hold._queue_timeline_hold_wake",
        lambda participant_id, reason=None, **kwargs: wakes.append(reason),
    )
    Trial.finalize_pending_trials()
    db.session.commit()

    trial = Trial.query.get(trial_id)
    assert trial.failed and trial.ready_for_feedback
    assert "trial_failed" in wakes


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_feedback_waits_until_the_trial_is_finalized(db_session, participant):
    """After async_post_trial commits, feedback waits for the re-check to finalize the trial."""
    network = _create_network(_chain_trial_maker(), get_experiment())
    trial = _add_complete_unfinalized_trial(
        network.head,
        participant,
        async_post_trial_requested=True,
        async_post_trial_complete=True,
    )
    trial_id = trial.id
    db.session.commit()

    assert not Trial.query.get(trial_id).ready_for_feedback

    Trial.recheck_finalization(trial_id)
    db.session.commit()

    trial = Trial.query.get(trial_id)
    assert trial.finalized and trial.ready_for_feedback


def _do_nothing():
    pass


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalize_skips_or_waits_for_a_locked_participant(db_session, participant):
    """While a request (e.g. ``participant.fail()``) holds the participant, the
    poller skips the trial and the post-commit re-check waits for the
    participant."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    network = _create_network(_chain_trial_maker(), get_experiment())
    trial = _add_complete_unfinalized_trial(network.head, participant)
    trial_id, participant_id = trial.id, participant.id
    db.session.commit()

    with db.engine.connect() as request:
        with request.begin():
            request.execute(
                text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
                {"id": participant_id},
            )
            assert Trial.get_trials_ready_to_finalize() == []
            request.execute(
                text("SELECT id FROM trial WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": trial_id},
            )
            db.session.rollback()

            db.session.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                Trial.recheck_finalization(trial_id)
            db.session.rollback()

    assert [t.id for t in Trial.get_trials_ready_to_finalize()] == [trial_id]
    with db.engine.connect() as worker, worker.begin():
        # Inserting a row that references the participant takes this lock.
        worker.execute(
            text("SELECT id FROM participant WHERE id = :id FOR KEY SHARE NOWAIT"),
            {"id": participant_id},
        )


class AnalyzedRecordingTrial(FinalizeBackstopTrial):
    run_async_post_trial = True

    def async_post_trial(self):
        pass

    def queue_async_post_trial(self):
        # The test trial maker is not on the timeline; record the request only.
        self.async_post_trial_requested = True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("failure", ["exception", "database_error"])
@pytest.mark.parametrize("failing_attempts", [0, 1, 2])
def test_deposit_callbacks_in_a_worker_never_expose_a_finalizable_trial(
    db_session, participant, monkeypatch, tmp_path, failure, failing_attempts
):
    """The finalization poller never sees a deposit before its callbacks have
    queued analysis. A failing hook's changes are discarded and the hook is
    retried; only a persistent failure fails the trial."""
    import io
    from pathlib import Path

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from psynet.asset import LocalStorage
    from psynet.async_job import AsyncJob, WorkerAsyncJob
    from psynet.media_upload import (
        _DEPOSIT_CALLBACK_ATTEMPTS,
        _process_recording,
        _receive_recording,
    )
    from psynet.trial.record import Recording

    deployment = {
        "deployment_id": "test-deployment",
        "is_local_deployment": True,
        "is_ssh_deployment": False,
    }
    monkeypatch.setattr("psynet.deployment_info.read", deployment.__getitem__)
    monkeypatch.setattr(LocalStorage, "on_deployed_server", lambda self: True)
    exp = get_experiment()
    network = _create_network(_chain_trial_maker(), exp)
    trial = AnalyzedRecordingTrial(
        experiment=exp,
        node=network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    db.session.add(trial)
    db.session.flush()
    asset, receipt = _reserve_trial_recording(trial, tmp_path / "assets")
    payload = (
        Path(__file__).resolve().parents[2]
        / "demos/experiments/imitation_chain_video/assets/example_recording.webm"
    ).read_bytes()
    asset.upload_max_bytes = len(payload)
    recording_id, trial_id = asset.id, trial.id
    db.session.commit()
    _receive_recording(
        recording_id, receipt["token"], io.BytesIO(payload), directory=tmp_path
    )

    after_deposit = Recording.after_deposit
    calls = []

    finalizable_during_callbacks = []

    def flaky_after_deposit(self):
        calls.append(self.id)
        # What the finalization poller sees from its own session meanwhile.
        with Session(db.engine) as poller:
            finalizable_during_callbacks.extend(
                poller.scalars(Trial.ready_to_finalize_id_select()).all()
            )
        if len(calls) > failing_attempts:
            return after_deposit(self)
        self.trial.answer = "changed by a failing hook"
        db.session.flush()
        if failure == "database_error":
            db.session.execute(text("SELECT * FROM missing_table"))
        raise RuntimeError("intentional deposit callback failure")

    monkeypatch.setattr(Recording, "after_deposit", flaky_after_deposit)
    job = WorkerAsyncJob(_process_recording, arguments={"recording_id": recording_id})
    db.session.add(job)
    db.session.flush()
    job_id = job.id
    db.session.commit()

    WorkerAsyncJob.call_function(job_id)

    job = db.session.get(AsyncJob, job_id, populate_existing=True)
    assert (job.finished, job.failed) == (True, False)
    recording = db.session.get(Recording, recording_id, populate_existing=True)
    assert (recording.upload_status, recording.deposited) == ("deposited", True)
    assert len(calls) == min(failing_attempts + 1, _DEPOSIT_CALLBACK_ATTEMPTS)
    assert trial_id not in finalizable_during_callbacks
    trial = db.session.get(Trial, trial_id, populate_existing=True)
    assert trial.answer == 1
    assert not trial.finalized
    if failing_attempts < _DEPOSIT_CALLBACK_ATTEMPTS:
        assert not trial.failed
        assert trial.async_post_trial_requested
    else:
        assert trial.failed_reason == "after_deposit_error"
        assert not trial.async_post_trial_requested


class CountingAnalysisTrial(FinalizeBackstopTrial):
    run_async_post_trial = True
    queued = []

    def async_post_trial(self):
        pass

    def queue_async_post_trial(self):
        type(self).queued.append(self.id)
        self.async_post_trial_requested = True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_async_post_trial_is_not_queued_twice_from_a_stale_trial(
    db_session, participant
):
    """The participant's request may hold a trial loaded before a recording
    worker's deposit queued analysis; it must not queue it again."""
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    network = _create_network(_chain_trial_maker(), get_experiment())
    trial = CountingAnalysisTrial(
        experiment=get_experiment(),
        node=network.head,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = 1
    trial.complete = True
    db.session.add(trial)
    db.session.commit()
    CountingAnalysisTrial.queued = []
    assert trial.async_post_trial_requested is False  # loaded in this session

    # Meanwhile the worker's deposit queues analysis and commits.
    with Session(db.engine) as worker, worker.begin():
        worker.execute(
            update(Trial)
            .where(Trial.id == trial.id)
            .values(async_post_trial_requested=True)
        )

    trial.check_if_can_run_async_post_trial()
    assert CountingAnalysisTrial.queued == []
