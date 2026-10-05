import psynet.experiment
from psynet.asset import LocalStorage, S3Storage  # noqa
from psynet.bot import Bot
from psynet.page import InfoPage
from psynet.prescreen import (
    FreeTappingRecordTest,
    REPPMarkersTest,
    REPPTappingCalibration,
    REPPVolumeCalibrationMarkers,
    REPPVolumeCalibrationMusic,
)
from psynet.timeline import Timeline


# Experiment
class Exp(psynet.experiment.Experiment):
    label = "REPP tests demo"

    # asset_storage = S3Storage("psynet-tests", "repp-tests")

    timeline = Timeline(
        # Volume calibration tests
        REPPVolumeCalibrationMarkers(),  # Use this for SMS experiments with markers
        REPPVolumeCalibrationMusic(),  # Use this for experiments using music
        REPPTappingCalibration(),  # Tapping instructions and calibration
        # Recording tests
        FreeTappingRecordTest(),  # Use this for unconstrained tapping experiment (without markers).
        InfoPage(
            "You passed the tapping recording test! Congratulations.", time_estimate=3
        ),
        REPPMarkersTest(),  # Use this for SMS tapping experiments (with markers).
        InfoPage("You passed the recording test! Congratulations.", time_estimate=3),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        from psynet.process import AsyncProcess

        assert not bot.failed
        processes = AsyncProcess.query.filter_by(participant_id=bot.id).all()
        assert all(not p.failed for p in processes)
        assert all(not p.pending for p in processes)
