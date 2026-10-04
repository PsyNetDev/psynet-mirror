"""
Checks that a failed Prolific participant who returns their submission is paid.

Failed participants reach the return-for-bonus flow from the unsuccessful end
logic. The simulated Prolific service reports every submission as returned.
"""

import dallinger.prolific

import psynet.experiment
from psynet.consent import NoConsent
from psynet.page import InfoPage
from psynet.participant import BONUS_STATUS_SUCCESS
from psynet.timeline import CodeBlock, PageMaker, Timeline

dallinger.prolific.DevProlificService.get_participant_submission = (
    lambda self, assignment_id, **kwargs: {"status": "RETURNED"}
)


def fail_participant(participant):
    """Fail the participant, as the unsuccessful end logic does."""
    participant.failed = True
    participant.failed_reason = "screened_out"


class Exp(psynet.experiment.Experiment):
    label = "Prolific return-for-bonus"
    config = {
        "prolific_workspace": "test_workspace",
        "prolific_project": "test_project",
        "prolific_enable_return_for_bonus": True,
        "prolific_pay_unsuccessful": False,
    }
    test_n_bots = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from dallinger.config import get_config

        get_config().set("recruiter", "devprolific")

    timeline = Timeline(
        NoConsent(),
        InfoPage("Some work worth paying for.", time_estimate=60),
        CodeBlock(fail_participant),
        PageMaker(
            lambda experiment, participant: (
                experiment.recruiter.request_return_for_bonus(participant)
            ),
            time_estimate=1,
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        assert bot.status == "returned"
        assert bot.bonus_status == BONUS_STATUS_SUCCESS
        assert bot.bonus > 0
