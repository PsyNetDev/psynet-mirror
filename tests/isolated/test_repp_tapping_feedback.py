from types import SimpleNamespace

from psynet.page import InfoPage
from psynet.prescreen import FreeTappingRecordTrial


def _feedback(**trial):
    return FreeTappingRecordTrial.show_feedback(
        SimpleNamespace(**trial), experiment=None, participant=None
    )


def test_tapping_feedback_handles_trials_failed_before_analysis():
    assert _feedback(failed=True, failed_reason="fail_async_processes") is None

    rejected = _feedback(
        failed=True,
        failed_reason="analysis",
        analysis={"num_resp_onsets_detected": 2},
    )
    assert isinstance(rejected, InfoPage)
