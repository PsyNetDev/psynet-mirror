import psynet.experiment
from psynet.consent import MainConsent
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.utils import get_logger

logger = get_logger()


class Exp(psynet.experiment.Experiment):
    label = "Lab Recruiter demo"

    timeline = Timeline(
        MainConsent(),
        InfoPage("You finished the experiment!", time_estimate=0),
    )

    def test_check_bot(self, bot):
        """Test that lab_recruiter_external_submission_url config works correctly."""
        super().test_check_bot(bot)

        # Test that the custom external submission URL is properly applied
        assert (
            self.recruiter.external_submission_url
            == "https://test-recruiter.example.com/tasks"
        )
