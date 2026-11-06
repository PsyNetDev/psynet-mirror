from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

from psynet.end import (
    EndLogic,
    RecordedSubmissionPage,
    RejectedConsentLogic,
    SuccessfulEndLogic,
    UnsuccessfulEndLogic,
)


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
        unsuccessful = UnsuccessfulEndLogic().debrief_participant(
            experiment, participant
        )
        rejected = RejectedConsentLogic().debrief_participant(experiment, participant)

    assert "Click Finish to return to your panel." in success.plain_text
    assert "Click Finish to finalize the session." not in success.plain_text
    assert "Click Finish to return to your panel." in unsuccessful.plain_text
    assert "send you back to your panel" not in unsuccessful.plain_text
    assert "We will return you to your panel in a few seconds." in rejected.plain_text
    assert "You may close this page." in rejected.plain_text


def test_end_pages_can_continue_by_themselves():
    experiment = MagicMock()
    with patch.object(SuccessfulEndLogic, "should_show_reward", False):
        page = SuccessfulEndLogic(auto_continue_seconds=3).debrief_participant(
            experiment, MagicMock()
        )
    assert (page.time_limit, page.time_limit_answer) == (3, "Finish")
    assert "This page continues by itself in 3 seconds." in page.plain_text
    assert "Click Finish" not in page.plain_text


def test_unsuccessful_end_explains_why_the_participant_stopped():
    """PsyNet explains its own failure tags, and an experiment can explain its own."""
    left = SimpleNamespace(
        failure_tags=["barrier:round", "hidden_while_waiting"], module_state=None
    )
    other = SimpleNamespace(failure_tags=["screening"], module_state=None)
    async_job = SimpleNamespace(
        failure_tags=["timeline_hold:job", "fail_on_timeout"], module_state=None
    )
    barrier_wait = SimpleNamespace(
        failure_tags=["timeline_hold:barrier:round", "fail_on_timeout"],
        module_state=None,
    )
    assert UnsuccessfulEndLogic().failure_reason(async_job) is None
    assert "waited too long" in UnsuccessfulEndLogic().failure_reason(barrier_wait)
    assert "switched away" in UnsuccessfulEndLogic().failure_reason(left)
    assert UnsuccessfulEndLogic().failure_reason(other) is None

    def failure_message(participant):
        if "screening" in participant.failure_tags:
            return "You didn't pass the hearing test."

    logic = UnsuccessfulEndLogic(failure_message=failure_message)
    assert logic.failure_reason(other) == "You didn't pass the hearing test."
    assert "switched away" in logic.failure_reason(left)
