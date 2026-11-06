from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from psynet.end import (
    EndLogic,
    RecordedSubmissionPage,
    RejectedConsentLogic,
    SuccessfulEndLogic,
    UnsuccessfulEndLogic,
)
from psynet.page import UnsuccessfulEndPage


def _reward_html(monkeypatch, time_reward, performance_reward):
    monkeypatch.setattr(
        "psynet.utils.get_config",
        lambda: SimpleNamespace(get=lambda key, default=None: "$"),
    )
    participant = SimpleNamespace(
        time_reward=time_reward,
        performance_reward=performance_reward,
    )
    return str(EndLogic().summarize_reward(None, participant))


def test_recorded_submission_page_renders_recruiter_submission_page():
    """Live confirmation HTML comes from the recruiter, not stored page copy."""
    experiment = MagicMock()
    experiment.recruiter.render_submission_page.return_value = "confirmation html"
    participant = MagicMock()
    page = RecordedSubmissionPage()

    with Flask(__name__).test_request_context("/timeline"):
        response = page.render(experiment, participant)

    assert response.get_data(as_text=True) == "confirmation html"
    assert response.headers["Cache-Control"] == "no-store"
    experiment.recruiter.render_submission_page.assert_called_once_with(participant)


def test_summarize_reward_omits_zero_performance_reward(monkeypatch):
    html = _reward_html(monkeypatch, time_reward=0.12, performance_reward=0.0)
    assert (
        "You will receive a reward of <strong>$0.12</strong> for the time you spent. "
        == html
    )
    assert "performance reward" not in html


def test_summarize_reward_includes_nonzero_performance_reward(monkeypatch):
    html = _reward_html(monkeypatch, time_reward=0.13, performance_reward=9.09)
    assert (
        "You will receive a reward of <strong>$0.13</strong> for the time you spent. "
        "You have also been awarded a performance reward of "
        "<strong>$9.09</strong>. " == html
    )
    assert "!" not in html


def test_summarize_reward_treats_sub_cent_performance_reward_as_zero(monkeypatch):
    html = _reward_html(monkeypatch, time_reward=1.0, performance_reward=0.004)
    assert "performance reward" not in html


def _identity_end_translator(*args, **kwargs):
    del args, kwargs
    return lambda *parts: parts[-1]


def test_lucid_debrief_uses_return_to_panel_copy():
    experiment = MagicMock()
    experiment.with_lucid_recruitment.return_value = True
    experiment.show_reward = False
    recruiter = MagicMock()
    recruiter.external_submit_url.return_value = "https://lucid.test/terminate"
    experiment.recruiter = recruiter
    participant = MagicMock()

    with (
        patch.object(SuccessfulEndLogic, "should_show_reward", False),
        patch.object(UnsuccessfulEndLogic, "should_show_reward", False),
        patch("psynet.end.get_translator", side_effect=_identity_end_translator),
    ):
        success = SuccessfulEndLogic().debrief_participant(experiment, participant)
        unsuccessful = UnsuccessfulEndLogic(
            failure_message="The study is full."
        ).debrief_participant(experiment, participant)
        rejected = RejectedConsentLogic().debrief_participant(experiment, participant)

    assert "Click Finish to return to your panel." in success.plain_text
    assert "Click Finish to finalize the session." not in success.plain_text
    assert "Click Finish to return to your panel." in unsuccessful.plain_text
    assert "send you back to your panel" not in unsuccessful.plain_text
    assert "The study is full." in unsuccessful.plain_text
    assert "We will return you to your panel in a few seconds." in rejected.plain_text
    assert "You may close this page." in rejected.plain_text


def test_unsuccessful_end_explains_why_the_participant_stopped():
    """PsyNet explains its own failure tags, and an experiment can explain its own."""
    slow = SimpleNamespace(
        failure_tags=["barrier:round", "timeout between barriers"], module_state=None
    )
    other = SimpleNamespace(failure_tags=["performance_check"], module_state=None)
    async_job = SimpleNamespace(
        failure_tags=["timeline_hold:wait_while", "fail_on_timeout"], module_state=None
    )
    barrier_wait = SimpleNamespace(
        failure_tags=["timeline_hold:barrier:round", "fail_on_timeout"],
        module_state=None,
    )
    waiting_page = SimpleNamespace(
        failure_tags=["while_loop:barrier:round", "fail_on_timeout"],
        module_state=None,
    )
    too_few = SimpleNamespace(
        failure_tags=["sync group below minimum size"], module_state=None
    )
    assert UnsuccessfulEndLogic().failure_reason(async_job) is None
    assert "waited too long" in UnsuccessfulEndLogic().failure_reason(barrier_wait)
    assert "waited too long" in UnsuccessfulEndLogic().failure_reason(waiting_page)
    assert "Too few members" in UnsuccessfulEndLogic().failure_reason(too_few)
    assert "took too long" in UnsuccessfulEndLogic().failure_reason(slow)
    assert UnsuccessfulEndLogic().failure_reason(other) is None
    assert (
        UnsuccessfulEndLogic(failure_message="The study is full.").failure_reason(other)
        == "The study is full."
    )

    def failure_message(participant):
        if "performance_check" in participant.failure_tags:
            return "You didn't pass the hearing test."

    logic = UnsuccessfulEndLogic(failure_message=failure_message)
    assert logic.failure_reason(other) == "You didn't pass the hearing test."
    assert "took too long" in logic.failure_reason(slow)

    assert UnsuccessfulEndLogic(failure_message="").failure_reason(slow) == ""
    silent = UnsuccessfulEndLogic(failure_message=lambda participant: "")
    assert silent.failure_reason(slow) == ""


def test_failure_message_errors_fall_back_to_builtin_reason(caplog):
    def failure_message(participant):
        raise RuntimeError("boom")

    participant = SimpleNamespace(
        id=7, failure_tags=["timeout between barriers"], module_state=None
    )
    reason = UnsuccessfulEndLogic(failure_message=failure_message).failure_reason(
        participant
    )
    assert "took too long" in reason
    assert "participant 7" in caplog.text


def test_rejected_consent_logic_refuses_failure_message():
    with pytest.raises(TypeError, match="failure_message"):
        RejectedConsentLogic(failure_message="Bye.")


def test_unsuccessful_end_page_points_failure_message_to_end_logic():
    with pytest.raises(TypeError, match="UnsuccessfulEndLogic"):
        UnsuccessfulEndPage(failure_message="You didn't pass screening.")
