from markupsafe import Markup

import psynet.experiment
from psynet.asset import asset
from psynet.modular_page import (
    AudioRecordControl,
    ModularPage,
    VideoPrompt,
    VideoRecordControl,
)
from psynet.page import wait_while
from psynet.timeline import (
    Event,
    MediaSpec,
    Module,
    PageMaker,
    ProgressDisplay,
    ProgressStage,
    Timeline,
    join,
)
from psynet.utils import get_logger

logger = get_logger()

# def make_js_fade_string(fade_duration):
#     return "{fade_in: %s, fade_out: %s}" % (fade_duration, fade_duration)


all_assets = {
    "flower": asset("local_only/flower.mp4", cache=True),
    "birds": asset("local_only/birds.mp4", cache=True),
    "funk-game-loop": asset("local_only/funk-game-loop.mp3", cache=True),
    "sync-test-video": asset("local_only/video-sync-test.mp4", cache=True),
    "sync-test-audio": asset("local_only/video-sync-test.wav", cache=True),
}


video_pages = join(
    PageMaker(
        lambda assets: ModularPage(
            "simple_video_prompt",
            VideoPrompt(
                assets["flower"],
                Markup(
                    """
                <h3>Example video prompt:</h3>
                <p><a href="https://commons.wikimedia.org/wiki/File:Water_lily_opening_bloom_20fps.ogv">SecretDisc</a>, <a href="https://creativecommons.org/licenses/by-sa/3.0">CC BY-SA 3.0</a>, via Wikimedia Commons</p>
                """
                ),
                mirrored=True,
            ),
        ),
        time_estimate=5,
    ),
    PageMaker(
        lambda assets: ModularPage(
            "video_play_window",
            VideoPrompt(
                assets["flower"],
                Markup(
                    """
                <h3>Example video prompt with play window:</h3>
                <p><a href="https://commons.wikimedia.org/wiki/File:Water_lily_opening_bloom_20fps.ogv">SecretDisc</a>, <a href="https://creativecommons.org/licenses/by-sa/3.0">CC BY-SA 3.0</a>, via Wikimedia Commons</p>
                """
                ),
                mirrored=True,
                play_window=[3, 4],
            ),
        ),
        time_estimate=5,
    ),
    PageMaker(
        lambda assets: ModularPage(
            "video_plus_audio",
            VideoPrompt(
                assets["birds"],
                "Here we play a video, muted, alongside an audio file.",
                mirrored=True,
                muted=True,
            ),
            media=MediaSpec(audio={"soundtrack": assets["funk-game-loop"]}),
            events={
                "playSoundtrack": Event(
                    is_triggered_by="promptStart",
                    delay=0.0,
                    js="psynet.audio.soundtrack.play()",
                )
            },
        ),
        time_estimate=5,
    ),
    PageMaker(
        lambda assets: ModularPage(
            "video_plus_audio_2",
            VideoPrompt(
                assets["sync-test-video"],
                """
                Here's a second version, where the video and audio both come from the same original recording.
                If everything is working properly, the video and the audio should be well-synchronized.
                """,
                mirrored=True,
                muted=True,
                play_window=[12, None],
            ),
            media=MediaSpec(
                audio={
                    "soundtrack": assets["sync-test-audio"],
                    # "soundtrack": "https://psynet.s3.amazonaws.com/tests/video-sync-test.wav"
                }
            ),
            events={
                "playSoundtrack": Event(
                    is_triggered_by="promptStart",
                    delay=0.0,
                    js="psynet.audio.soundtrack.play()",
                )
            },
        ),
        time_estimate=5,
    ),
    PageMaker(
        lambda assets: ModularPage(
            "video_plus_video_record",
            VideoPrompt(
                assets["birds"],
                "Here we play a video and instruct the user to record an audio response.",
                mirrored=True,
                muted=True,
                play_window=[0, 4],
            ),
            AudioRecordControl(
                controls=True,
                duration=4.0,
                bot_response_media="example_audio_recording.wav",
            ),
            progress_display=ProgressDisplay(stages=[ProgressStage(time=4)]),
            media=MediaSpec(audio={"soundtrack": assets["funk-game-loop"]}),
            events={
                "playSoundtrack": Event(
                    is_triggered_by="promptStart",
                    delay=0.0,
                    js="psynet.audio.soundtrack.play()",
                ),
                "stopSoundtrack": Event(
                    is_triggered_by="promptStart",
                    delay=4.0,
                    js="psynet.audio.soundtrack.stop()",
                ),
            },
        ),
        time_estimate=5,
    ),
    PageMaker(
        lambda assets: ModularPage(
            "video_prompt_plus_video_record",
            VideoPrompt(
                assets["birds"],
                text="""
                Here we play a video and instruct the user to record a video response after a countdown.
                The soundtrack also has a 0.5 second fade-in and fade-out.
                """,
                mirrored=True,
                muted=True,
                play_window=[0, 4],
                width="180px",
            ),
            VideoRecordControl(
                controls=True,
                duration=4.0,
                show_preview=True,
                bot_response_media="example_video_recording.webm",
            ),
            progress_display=ProgressDisplay(
                stages=[
                    ProgressStage(
                        [0.0, 1.0], "Recording in 3 seconds...", color="grey"
                    ),
                    ProgressStage(
                        [1.0, 2.0], "Recording in 2 seconds...", color="grey"
                    ),
                    ProgressStage(
                        [2.0, 3.0], "Recording in 1 seconds...", color="grey"
                    ),
                    ProgressStage([3.0, 4.0 + 3.0], "Recording!", color="red"),
                ],
            ),
            media=MediaSpec(audio={"soundtrack": assets["funk-game-loop"]}),
            events={
                "trialPrepare": Event(is_triggered_by=None),
                "promptStart": Event(is_triggered_by="trialStart", delay=3.0),
                "recordStart": Event(is_triggered_by="trialStart", delay=3.0),
                "playSoundtrack": Event(
                    is_triggered_by="promptStart",
                    delay=0.0,
                    js="psynet.audio.soundtrack.play({fade_in: 0.5, fade_out: 0.5})",
                ),
                "stopSoundtrack": Event(
                    is_triggered_by="promptStart",
                    delay=4.0,
                    js="psynet.audio.soundtrack.stop()",
                ),
            },
        ),
        time_estimate=5,
    ),
    ModularPage(
        "video_record_page",
        "This page lets you record video and sound from camera and microphone while also doing a simultaneous screen recording.",
        VideoRecordControl(
            duration=5.0,
            recording_source="both",
            show_preview=True,
            controls=True,
            bot_response_media={
                "camera": "example_video_recording.webm",
                "screen": "example_video_recording.webm",  # This isn't actually a screen recording
            },
        ),
        time_estimate=5,
        progress_display=ProgressDisplay([ProgressStage(time=5.0)]),
    ),
    wait_while(
        lambda participant: (
            not (
                participant.assets["video_record_page_camera"].deposited
                and participant.assets["video_record_page_screen"].deposited
            )
        ),
        expected_wait=5.0,
        log_message="Waiting for video recordings to be deposited",
    ),
    PageMaker(
        lambda participant: ModularPage(
            "video_playback",
            VideoPrompt(
                participant.assets["video_record_page_camera"],
                Markup(
                    f"""
                        Here's the camera recording you just made.
                        <br>
                        Click <a href="{participant.assets["video_record_page_screen"].url}">this link</a> to download the corresponding screen recording.
                    """
                ),
                mirrored=True,
                width="400px",
            ),
        ),
        time_estimate=5,
    ),
)


class Exp(psynet.experiment.Experiment):
    label = "Video demo"

    timeline = Timeline(
        Module(
            "video_demo",
            video_pages,
            assets=all_assets,
        ),
    )
