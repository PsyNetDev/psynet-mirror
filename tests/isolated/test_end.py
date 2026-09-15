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


def test_recorded_submission_page_renders_recruiter_exit_response():
    """Live confirmation HTML comes from exit_response, not stored page copy."""
    experiment = MagicMock()
    experiment.recruiter.exit_response.return_value = "confirmation html"
    participant = MagicMock()
    page = RecordedSubmissionPage()

    with Flask(__name__).test_request_context("/timeline"):
        response = page.render(experiment, participant)

    assert response.get_data(as_text=True) == "confirmation html"
    assert response.headers["Cache-Control"] == "no-store"
    experiment.recruiter.exit_response.assert_called_once_with(experiment, participant)


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
