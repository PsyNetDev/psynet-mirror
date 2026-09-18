from markupsafe import Markup

import psynet.experiment
from psynet.asset import asset
from psynet.consent import AudiovisualConsent, MainConsent
from psynet.js_synth import Chord, InstrumentTimbre, JSSynth, Note, Rest, ShepardTimbre
from psynet.modular_page import (
    AudioMeterControl,
    AudioPrompt,
    AudioRecordControl,
    ModularPage,
    SliderControl,
    TappingAudioMeterControl,
    VideoPrompt,
    VideoRecordControl,
)
from psynet.page import InfoPage, wait_while
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


def get_timeline():
    return Timeline(
        MainConsent(),
        AudiovisualConsent(),
        Module(
            "audio_demo",
            example_js_synth_1,
            example_js_synth_2,
            example_js_synth_3,
            example_js_synth_4,
            example_js_synth_5,
            example_audio_page,
            example_audio_page_1,
            example_audio_page_2,
            example_audio_page_2b,
            example_audio_page_2c,
            example_audio_page_3,
            example_audio_meter,
            example_record_page,
            example_listen_then_record_page,
            example_record_audio_video,
            example_audio_meter_calibrate_with_audio,
            example_audio_meter_calibrate_with_tapping,
            example_preloading,
            assets=all_assets,
        ),
    )


all_assets = {
    "bier": asset("local_only/bier.wav", cache=True),
    "file-concatenated": asset("local_only/file_concatenated.mp3", cache=True),
    "funk-game-loop": asset("local_only/funk-game-loop.mp3", cache=True),
    "train-1": asset("local_only/train1.wav", cache=True),
}

example_js_synth_1 = ModularPage(
    "js_synth",
    JSSynth(
        "The JS synthesizer uses by default a harmonic complex tone as the timbre.",
        [
            Note(60, pan=-1),
            Note(64, pan=-1),
            Note(67, pan=-1),
            Rest(duration=1.0),
            Note(59, pan=1),
            Note(62, pan=1),
            Note(67, pan=1),
        ],
        controls=True,
    ),
    time_estimate=5,
)

example_js_synth_2 = ModularPage(
    "js_synth",
    JSSynth(
        "It is also possible to select various instrument sounds, for example the piano.",
        [
            Note(60),
            Note(63),
            Note(67),
        ],
        timbre=InstrumentTimbre("piano"),
        default_duration=0.5,
        default_silence=0.25,
    ),
    time_estimate=5,
)

example_js_synth_3 = ModularPage(
    "js_synth",
    JSSynth(
        "We can manipulate individual notes with a slider.",
        [
            Note(60),
            Note(63),
            Note(67),
        ],
        timbre=InstrumentTimbre("piano"),
        default_duration=0.5,
        default_silence=0.25,
    ),
    SliderControl(start_value=63, min_value=57, max_value=70),
    time_estimate=5,
    events={
        "playMelody": Event(
            is_triggered_by="sliderChange",
            js=(
                "psynet.getJsSynthState().stimulus.notes[1].pitches = "
                "[info.outputValue]; psynet.trial.restart();"
            ),
        ),
        "disableSlider": Event(
            is_triggered_by="promptStart",
            js="psynet.page.control.slider.disable(true);",
        ),
        "enableSlider": Event(
            is_triggered_by="promptEnd", js="psynet.page.control.slider.enable(true);"
        ),
    },
)

example_js_synth_4 = ModularPage(
    "js_synth",
    JSSynth(
        "These chords are played with Shepard tones.",
        [
            Chord([60, 64, 67], pan=-1),
            Chord([59, 62, 67], pan=1),
            Chord([60, 64, 67], pan=[-1, 0, 1]),
        ],
        timbre=ShepardTimbre(),
    ),
    time_estimate=5,
)

host_dir = "https://s3.eu-west-1.amazonaws.com/media.pmcharrison.com/music/westerkerk-carillon-sample-library/mp3"

example_js_synth_5 = ModularPage(
    "js_synth",
    JSSynth(
        "These chords are played using a custom sampler.",
        [
            Note(48),
            Note(50),
            Note(52),
        ],
        timbre=InstrumentTimbre(
            type="carillon",
            samples={
                "C3": f"{host_dir}/36-c3.mp3",
                "D3": f"{host_dir}/38-d3.mp3",
                "E3": f"{host_dir}/40-e3.mp3",
            },
        ),
    ),
    time_estimate=5,
)

example_preloading = PageMaker(
    lambda assets: InfoPage(
        Markup(
            """
        <p>
            This page demonstrates audio preloading.
            A progress bar fills up on the bottom of the screen
            as the audio files are loaded into the client's browser.
            Once these audio files are loaded, you can access them programmatically.
        </p>
        <p>
            If you're running this demo locally, the audio files will load too
            fast for you to see the progress bar. However, you can simulate
            a slower internet connection by using the Developer Options
            of your browser.
            Note how the buttons only become enabled once the audio has finished loading.
        </p>
        <div id="audio-preloading-controls">
            <ul>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.bier.play();">Play 'bier'.</button></li>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.bier.stop();">Stop 'bier'.</button></li>
            </ul>
            <ul>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.funk_game_loop.play();">Play 'funk_game_loop'.</button></li>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.funk_game_loop.stop();">Stop 'funk_game_loop'.</button></li>
            </ul>
            <ul>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.honey_bee.play();">Play 'honey_bee'.</button></li>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.honey_bee.stop();">Stop 'honey_bee'.</button></li>
            </ul>
            <ul>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.there_it_is.play();">Play 'there_it_is'.</button></li>
                <li> <button type="button" class="btn btn-primary wait-for-media-load" onclick="psynet.audio.there_it_is.stop();">Stop 'there_it_is'.</button></li>
            </ul>
        </div>
        """
        ),
        media=MediaSpec(
            audio={
                "bier": assets["bier"],
                "batch": {
                    "url": assets["file-concatenated"],
                    "ids": ["funk_game_loop", "honey_bee", "there_it_is"],
                    "type": "batch",
                },
            }
        ),
        css_links=["/static/audio-preloading.css"],
    ),
    time_estimate=5,
)

example_audio_meter = ModularPage(
    "audio_meter",
    """
    This page shows an audio meter.
    """,
    AudioMeterControl(calibrate=False),
    time_estimate=5,
)

example_audio_meter_calibrate = ModularPage(
    "audio_meter",
    "Here you can experiment with different audio meter parameters.",
    AudioMeterControl(calibrate=True),
    time_estimate=5,
)

example_audio_meter_calibrate_with_audio = PageMaker(
    lambda assets: ModularPage(
        "audio_meter",
        AudioPrompt(
            assets["train-1"],
            "The default meter parameters are designed to work well for music playback.",
            loop=True,
        ),
        AudioMeterControl(calibrate=True),
    ),
    time_estimate=5,
)

example_audio_meter_with_audio = PageMaker(
    lambda assets: ModularPage(
        "audio_meter",
        AudioPrompt(
            assets["train-1"],
            "This page shows an audio meter alongside an audio stimulus.",
            loop=True,
        ),
        AudioMeterControl(calibrate=True),
    ),
    time_estimate=5,
)

example_audio_meter_calibrate_with_tapping = ModularPage(
    "audio_meter",
    """
    The TappingAudioMeterControl class is a version of the AudioMeterControl class
    with defaults specialised for tapping experiments. In particular,
    we disable the clipping warning, decrease the smoothing,
    and increase the grace period for the
    too-high warning, to make sure that the short loud tap doesn't cause
    a warning message.
    """,
    TappingAudioMeterControl(calibrate=True),
    time_estimate=5,
)

example_audio_page = PageMaker(
    lambda assets: ModularPage(
        "audio_page",
        AudioPrompt(
            assets["bier"],
            "This page illustrates a simple audio page with one stimulus.",
            loop=False,
            controls=False,
        ),
    ),
    time_estimate=5,
)

example_audio_page_1 = PageMaker(
    lambda assets: ModularPage(
        "audio_page",
        AudioPrompt(
            assets["bier"],
            "This page loops the same stimulus.",
            loop=True,
            controls=False,
        ),
    ),
    time_estimate=5,
)

example_audio_page_2 = PageMaker(
    lambda assets: ModularPage(
        "audio_page",
        AudioPrompt(
            assets["bier"],
            """
        This page adds audio playback controls.
        We've also set start_trial_automatically=False, meaning that the
        user will have to start the audio themselves.
        """,
            controls=True,
            loop=False,
        ),
        start_trial_automatically=False,
    ),
    time_estimate=5,
)

example_audio_page_2b = PageMaker(
    lambda assets: ModularPage(
        "audio_page",
        AudioPrompt(
            assets["bier"],
            """
        This page customizes the audio controls to only display
        a 'Play again' button.
        """,
            # If the user provides a dictionary, then the keys should
            # correspond to built-in controls, and the values (optional)
            # should correspond to the desired names for those controls.
            # Here the user has just selected the play control
            # and named it 'Play again'.
            controls={"Play": "Play again"},
            loop=False,
        ),
        start_trial_automatically=True,
    ),
    time_estimate=5,
)

example_audio_page_2c = PageMaker(
    lambda assets: ModularPage(
        "audio_page",
        prompt=(
            "This page shows how you can access audio stimuli outside of Audio Prompts. "
            "This can be helpful for achieving more complex audio sequences."
        ),
        media=MediaSpec(
            audio={
                "stimulus_1": assets["bier"],
                "stimulus_2": assets["train-1"],
            }
        ),
        events={
            "playStimulus1": Event(
                is_triggered_by="trialStart",
                js="psynet.audio.stimulus_1.play();",
                message="Playing stimulus 1...",
                message_color="blue",
            ),
            "playStimulus2": Event(
                is_triggered_by="audioFinished: stimulus_1",
                delay=0.5,
                js="psynet.audio.stimulus_2.play();",
                message="Playing stimulus 2...",
                message_color="green",
            ),
            "responseEnable": Event(
                is_triggered_by="playStimulus2",
                delay=1.0,
            ),
            "submitEnable": Event(
                is_triggered_by="responseEnable",
                delay=0.0,
            ),
        },
        progress_display=ProgressDisplay([], show_bar=False),
    ),
    time_estimate=5,
)

example_audio_page_3 = PageMaker(
    lambda assets: ModularPage(
        "audio_page",
        AudioPrompt(
            assets["train-1"],
            """
        This page illustrates a 'play window' combined with fade-in and loop.
        """,
            play_window=[5, 9],
            fade_in=0.75,
            # Note: fade_out is also supported in theory, but users are warned that
            # the timing is unreliable when the audio device has high latency.
            loop=True,
            controls=True,
        ),
    ),
    time_estimate=5,
)

example_record_page = join(
    ModularPage(
        "audio_record_page_1",
        "This page lets you record audio.",
        AudioRecordControl(
            duration=3.0,
            show_meter=True,
            controls=True,
            auto_advance=False,
            bot_response_media="example_recordings/response_2__record_page.wav",
        ),
        time_estimate=5,
        progress_display=ProgressDisplay(
            stages=[
                ProgressStage([0.0, 3.0], "Recording...", "red"),
            ],
        ),
    ),
    wait_while(
        lambda participant: not participant.assets["audio_record_page_1"].deposited,
        expected_wait=5.0,
        log_message="Waiting for the recording to finish uploading",
    ),
    PageMaker(
        lambda participant: ModularPage(
            "playback",
            AudioPrompt(
                participant.assets["audio_record_page_1"],
                "Here's the recording you just made.",
            ),
        ),
        time_estimate=5,
    ),
)


example_listen_then_record_page = PageMaker(
    lambda assets: ModularPage(
        "audio_record_page_2",
        AudioPrompt(
            assets["funk-game-loop"],
            text="""
            Here we play audio then activate the recorder 3 seconds afterwards.
            """,
            play_window=[0, 5.0],
        ),
        AudioRecordControl(
            duration=1.0,
            show_meter=True,
            controls=True,
            auto_advance=False,
            bot_response_media="example_recordings/response_4__record_page.wav",
        ),
        events={"recordStart": Event(is_triggered_by="trialStart", delay=3.0)},
        progress_display=ProgressDisplay(
            stages=[
                ProgressStage([0.0, 3.0], "Waiting to record..."),
                ProgressStage([3.0, 4.0], "Recording...", "red"),
                ProgressStage(
                    [4.0, 5.0], "Finished recording.", "green", persistent=True
                ),
            ],
        ),
    ),
    time_estimate=5,
)


example_record_audio_video = join(
    PageMaker(
        lambda assets: ModularPage(
            "video_record_page",
            AudioPrompt(
                assets["funk-game-loop"],
                text="""
                This page plays audio and records video after a couple of seconds.
                It'll work best if you wear headphones.
                The red portion of the progress bar identifies the period when the video
                will be recording.
                Note how we overrode the 'trialPrepare' event, meaning that the
                trial does not start itself automatically;
                instead the trial only starts once the user explicitly presses the
                'Start recording' button.
                """,
                play_window=[0, 4.6],
                fade_in=0.2,
            ),
            VideoRecordControl(
                duration=2.0,
                recording_source="camera",
                show_preview=True,
                show_meter=False,
                controls=True,
                loop_playback=False,
                auto_advance=True,
                bot_response_media="example_recordings/response_5__record_page.webm",
            ),
            progress_display=ProgressDisplay(
                stages=[
                    ProgressStage([0.0, 2.6], "Waiting to record...", color="grey"),
                    ProgressStage([2.6, 4.0], "Recording!", color="red"),
                    ProgressStage([4.0, 4.6], "Recording finished.", color="green"),
                ],
            ),
            events={
                "trialPrepare": Event(is_triggered_by=None),
                "audioStart": Event(is_triggered_by="trialStart", delay=0.0),
                "recordStart": Event(is_triggered_by="trialStart", delay=2.6),
            },
        ),
        time_estimate=5,
    ),
    PageMaker(
        lambda participant: ModularPage(
            "playback",
            VideoPrompt(
                participant.assets["video_record_page"],
                "Here's the recording you just made.",
                mirrored=True,
            ),
        ),
        time_estimate=5,
    ),
)


class Exp(psynet.experiment.Experiment):
    timeline = get_timeline()

    @property
    def ad_requirements(self):
        return super().ad_requirements + [
            'You must be wearing <span style="font-weight: bold;">headphones</span> and sitting in a quiet place.'
        ]

    @property
    def ad_payment_information(self):
        return (
            super().ad_payment_information
            + '<br>Send us your <span style="font-weight: bold;">bank account information</span> to receive refunds.'
        )
