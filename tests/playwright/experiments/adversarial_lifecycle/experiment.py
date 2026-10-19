import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Page, Timeline


class RejectUntilAcceptedPage(Page):
    def __init__(self):
        super().__init__(
            label="reject_until_accepted",
            time_estimate=1,
            template_fragment_str="""
                <p id="adversarial-rejection-page">
                    Rejection retry page
                </p>
            """,
        )

    def validate(self, response, **kwargs):
        if response.answer != "accepted":
            return "Please submit the accepted answer."
        return None

    def get_bot_response(self, experiment, bot):
        return "accepted"


class ListenerPage(Page):
    def __init__(self, page_name):
        self.page_name = page_name
        super().__init__(
            label=f"listener_{page_name}",
            time_estimate=1,
            template_fragment_str=f"""
                <p id="listener-page" data-page-name="{page_name}">
                    Listener page {page_name}
                </p>
            """,
            js_vars={"adversarial_listener": {"page_name": page_name}},
            js_page_modules=["/static/listener-page.js"],
            save_answer=False,
        )

    def get_bot_response(self, experiment, bot):
        return None


class TrackedTimerPage(Page):
    def __init__(self):
        super().__init__(
            label="tracked_timer",
            time_estimate=1,
            template_fragment_str="""
                <p id="tracked-timer-page">
                    Tracked timer page
                </p>
            """,
            js_page_modules=["/static/tracked-timer-page.js"],
        )

    def get_bot_response(self, experiment, bot):
        return None


class AudioFadeOutPage(Page):
    def __init__(self):
        super().__init__(
            label="audio_fade_out",
            time_estimate=1,
            template_fragment_str="""
                <p id="audio-fade-out-page">
                    Audio fade-out page
                </p>
            """,
            js_page_modules=["/static/audio-fade-out-page.js"],
        )

    def get_bot_response(self, experiment, bot):
        return None


class OverlappingAudioStopPage(Page):
    def __init__(self):
        super().__init__(
            label="overlapping_audio_stop",
            time_estimate=1,
            template_fragment_str="""
                <p id="overlapping-audio-stop-page">
                    Overlapping audio stop page
                </p>
            """,
            js_page_modules=["/static/overlapping-audio-stop-page.js"],
        )

    def get_bot_response(self, experiment, bot):
        return None


class Exp(psynet.experiment.Experiment):
    label = "Adversarial lifecycle test"

    timeline = Timeline(
        RejectUntilAcceptedPage(),
        TrackedTimerPage(),
        InfoPage("Timer cleanup checkpoint", time_estimate=1),
        AudioFadeOutPage(),
        InfoPage("Audio fade-out checkpoint", time_estimate=1),
        OverlappingAudioStopPage(),
        ListenerPage("first"),
        InfoPage("Listener cleanup checkpoint", time_estimate=1),
        ListenerPage("second"),
        InfoPage("Adversarial lifecycle complete", time_estimate=1),
    )
