"""Private recording transport fixture; production controls remain disabled."""

import psynet.experiment
from psynet.modular_page import ModularPage, VideoPrompt, VideoRecordControl
from psynet.page import InfoPage, wait_while
from psynet.timeline import PageMaker, Timeline


class AsyncVideoControl(VideoRecordControl):
    _async_upload = True


class Exp(psynet.experiment.Experiment):
    label = "Asynchronous recording test"
    timeline = Timeline(
        ModularPage(
            "recording",
            "Record a short clip.",
            AsyncVideoControl(
                duration=3, record_audio=False, controls=True, show_preview=True
            ),
            time_estimate=3,
            save_answer="recorded_video",
        ),
        InfoPage("Independent page reached.", time_estimate=1),
        wait_while(
            lambda participant: not participant.assets["recording"].deposited,
            expected_wait=0,
            max_wait_time=45,
        ),
        PageMaker(
            lambda participant: ModularPage(
                "playback",
                VideoPrompt(
                    participant.var.recorded_video["camera_url"],
                    "Uploaded clip.",
                    controls=True,
                    hide_when_finished=False,
                    muted=True,
                ),
                time_estimate=3,
            ),
            time_estimate=3,
        ),
    )
