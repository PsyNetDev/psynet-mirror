import json
import random
from importlib import resources
from os.path import exists as file_exists
from os.path import join as join_path
from random import shuffle
from typing import List, Optional

from markupsafe import Markup

from psynet.asset import ExternalAsset
from psynet.bot import Bot
from psynet.modular_page import (
    AudioMeterControl,
    AudioPrompt,
    AudioRecordControl,
    ColorPrompt,
    ImagePrompt,
    ModularPage,
    PushButtonControl,
    RadioButtonControl,
    TextControl,
)
from psynet.page import InfoPage, UnsuccessfulEndPage, wait_while
from psynet.timeline import (
    CodeBlock,
    Event,
    Module,
    PageMaker,
    ProgressDisplay,
    ProgressStage,
    conditional,
    join,
)
from psynet.trial.audio import AudioRecordTrial
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import get_logger, get_translator

from .vocabtest import BibleVocab, WikiVocab  # noqa: F401

logger = get_logger()

_ = get_translator()
_p = get_translator(context=True)


class REPPVolumeCalibration(Module):
    def __init__(
        self,
        label,
        materials_url: str = "https://s3.amazonaws.com/repp-materials",
        min_time_on_calibration_page: float = 5.0,
        time_estimate_for_calibration_page: float = 10.0,
    ):
        super().__init__(
            label,
            join(
                self.introduction,
                self.volume_calibration(
                    min_time_on_calibration_page,
                    time_estimate_for_calibration_page,
                ),
            ),
            assets={
                "volume_calibration_audio": self.asset_calibration_audio(materials_url),
                "rules_image": self.asset_rules(materials_url),
            },
        )

    def asset_calibration_audio(self, materials_url):
        raise NotImplementedError

    def asset_rules(self, materials_url):
        return ExternalAsset(url=materials_url + "/REPP-image_rules.png")

    @property
    def introduction(self):
        return PageMaker(
            lambda assets: InfoPage(
                Markup(
                    f"""
                      <h3>Attention</h3>
                      <hr>
                      <b>Throughout the experiment, it is very important to <b>ONLY</b> use the laptop speakers and be in a silent environment.
                      <br><br>
                      <i>Please do not use headphones, earphones, external speakers, or wireless devices (unplug or deactivate them now)</i>
                      <hr>
                      <img style="width:70%" src="{assets["rules_image"].url}" alt="rules_image">
                      """
                ),
            ),
            time_estimate=5,
        )

    def volume_calibration(
        self,
        min_time_on_calibration_page,
        time_estimate_for_calibration_page,
    ):
        return PageMaker(
            lambda assets: ModularPage(
                "volume_test",
                AudioPrompt(
                    assets["volume_calibration_audio"],
                    self.calibration_instructions,
                    loop=True,
                ),
                self.AudioMeter(min_time=min_time_on_calibration_page, calibrate=False),
            ),
            time_estimate=time_estimate_for_calibration_page,
        )

    class AudioMeter(AudioMeterControl):
        pass

    @property
    def calibration_instructions(self):
        return Markup(
            f"""
            <h3>Volume test</h3>
            <hr>
            <h4>We will begin by calibrating your audio volume:</h4>
            <ol>
                <li>{self.what_are_we_playing}</li>
                <li>Set the volume in your laptop to approximately 90% of the maximum.</li>
                <li><b>The sound meter</b> below indicates whether the audio volume is at the right level.</li>
                <li>If necessary, turn up the volume on your laptop until the sound meter consistently indicates that
                the volume is <b style="color:green;">"just right"</b>.
            </ol>
            <hr>
            """
        )

    @property
    def what_are_we_playing(self):
        return "A sound is playing to help you find the right volume in your laptop speakers."


class REPPVolumeCalibrationMusic(REPPVolumeCalibration):
    """
    This is a volume calibration test to be used when implementing SMS experiments with music stimuli and REPP. It contains
    a page with general technical requirements of REPP and a volume calibration test with a visual sound meter
    and stimulus customized to help participants find the right volume to use REPP.

    Parameters
    ----------
    label : string
        The label for the REPPVolumeCalibration test, default: "repp_volume_calibration_music".

    materials_url: string
        The location of the REPP materials, default: https://s3.amazonaws.com/repp-materials.

    min_time_on_calibration_page : float
        Minimum time (in seconds) that the participant must spend on the calibration page, default: 5.0.

    time_estimate_for_calibration_page : float
        The time estimate for the calibration page, default: 10.0.
    """

    def __init__(
        self,
        label="repp_volume_calibration_music",
        materials_url: str = "https://s3.amazonaws.com/repp-materials",
        min_time_on_calibration_page: float = 5.0,
        time_estimate_for_calibration_page: float = 10.0,
    ):
        super().__init__(
            label,
            materials_url,
            min_time_on_calibration_page,
            time_estimate_for_calibration_page,
        )

    def asset_calibration_audio(self, materials_url):
        return ExternalAsset(
            url=materials_url + "/calibrate.prepared.wav",
        )

    class AudioMeter(AudioMeterControl):
        decay = {"display": 0.1, "high": 0.1, "low": 0.1}
        threshold = {"high": -12, "low": -22}
        grace = {"high": 0.0, "low": 1.5}
        warn_on_clip = True
        msg_duration = {"high": 0.25, "low": 0.25}

    @property
    def what_are_we_playing(self):
        return "A music clip is playing to help you find the right volume in your laptop speakers."


class REPPVolumeCalibrationMarkers(REPPVolumeCalibration):
    """
    This is a volume calibration test to be used when implementing SMS experiments with metronome sounds and REPP. It contains
    a page with general technical requirements of REPP and it then plays a metronome sound to help participants find the right volume to use REPP.

    Parameters
    ----------
    label : string
        The label for the REPPVolumeCalibration test, default: "repp_volume_calibration_music".

    materials_url: string
        The location of the REPP materials, default: https://s3.amazonaws.com/repp-materials.

    min_time_on_calibration_page : float
        Minimum time (in seconds) that the participant must spend on the calibration page, default: 5.0.

    time_estimate_for_calibration_page : float
        The time estimate for the calibration page, default: 10.0.
    """

    def __init__(
        self,
        label="repp_volume_calibration_markers",
        materials_url: str = "https://s3.amazonaws.com/repp-materials",
        min_time_on_calibration_page: float = 5.0,
        time_estimate_for_calibration_page: float = 10.0,
    ):
        super().__init__(
            label,
            materials_url,
            min_time_on_calibration_page,
            time_estimate_for_calibration_page,
        )

    def asset_calibration_audio(self, materials_url):
        return ExternalAsset(
            url=materials_url + "/only_markers.wav",
        )

    class AudioMeter(AudioMeterControl):
        decay = {"display": 0.1, "high": 0.1, "low": 0}
        threshold = {"high": -5, "low": -10}
        grace = {"high": 0.2, "low": 1.5}
        warn_on_clip = False
        msg_duration = {"high": 0.25, "low": 0.25}

    @property
    def what_are_we_playing(self):
        return "We are playing a sound similar to the ones you will hear during the experiment."


class REPPTappingCalibration(Module):
    """
    This is a tapping calibration test to be used when implementing SMS experiments with REPP.
    It is also containing the main instructions about how to tap using this technology.

    Parameters
    ----------
    label : string
        The label for the REPPTappingCalibration test, default: "repp_tapping_calibration".

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 10.0.

    min_time_before_submitting : float
        Minimum time to wait (in seconds) while the music plays and the participant cannot submit a response, default: 5.0.

    materials_url: string
        The location of the REPP materials, default: https://s3.amazonaws.com/repp-materials.
    """

    def __init__(
        self,
        label="repp_tapping_calibration",
        time_estimate_per_trial: float = 10.0,
        min_time_before_submitting: float = 5.0,
        materials_url: str = "https://s3.amazonaws.com/repp-materials",
    ):
        super().__init__(
            label,
            join(
                PageMaker(
                    lambda assets: ModularPage(
                        label,
                        self.instructions_text(assets),
                        self.AudioMeter(
                            min_time=min_time_before_submitting, calibrate=False
                        ),
                    ),
                    time_estimate=time_estimate_per_trial,
                ),
            ),
            assets={
                "tapping_instructions_image": self.instructions_asset(materials_url),
            },
        )

    def instructions_asset(self, materials_url):
        return ExternalAsset(
            url=materials_url + "/tapping_instructions.jpg",
        )

    def instructions_text(self, assets):
        return Markup(
            f"""
            <h3>You will now practice how to tap on your laptop</h3>
            <b>Please always tap on the surface of your laptop using your index finger (see picture)</b>
            <ul>
                <li>Practice tapping and check that the level of your tapping is <b style="color:green;">"just right"</b>.</li>
                <li><i style="color:red;">Do not tap on the keyboard or tracking pad, and do not tap using your nails or any object</i>.</li>
                <li>If your tapping is <b style="color:red;">"too quiet!"</b>, try tapping louder or on a different location on your laptop.</li>
            </ul>
            <img style="width:70%" src="{assets["tapping_instructions_image"].url}"  alt="image_rules">
            """
        )

    class AudioMeter(AudioMeterControl):
        decay = {"display": 0.1, "high": 0.1, "low": 0}
        threshold = {"high": -12, "low": -20}
        grace = {"high": 0.2, "low": 1.5}
        warn_on_clip = False
        msg_duration = {"high": 0.25, "low": 0.25}


class NumpySerializer(json.JSONEncoder):
    def default(self, obj):
        import numpy as np

        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        else:
            return super().default(obj)


class FreeTappingRecordTrial(AudioRecordTrial, StaticTrial):
    def show_trial(self, experiment, participant):
        return ModularPage(
            "free_tapping_record",
            AudioPrompt(
                self.definition["url_audio"],
                Markup(
                    """
                    <h4>Tap a steady beat</h4>
                    """
                ),
            ),
            AudioRecordControl(
                duration=self.definition["duration_rec_sec"],
                show_meter=False,
                controls=False,
                auto_advance=False,
                bot_response_media=resources.files("psynet")
                / "resources/repp/free_tapping_record.wav",
            ),
            time_estimate=self.time_estimate,
            progress_display=ProgressDisplay(
                stages=[
                    ProgressStage(
                        self.definition["duration_rec_sec"],
                        "Recording... Start tapping!",
                        "red",
                        persistent=True,
                    ),
                ],
            ),
        )

    def analyze_recording(self, audio_file: str, output_plot: str):
        from repp.analysis import REPPAnalysis
        from repp.config import sms_tapping

        plot_title = "Participant {}".format(self.participant_id)
        repp_analysis = REPPAnalysis(config=sms_tapping)
        _, _, stats = repp_analysis.do_analysis_tapping_only(
            audio_file, plot_title, output_plot
        )
        # output
        num_resp_onsets_detected = stats["num_resp_onsets_detected"]
        min_responses_ok = (
            num_resp_onsets_detected > self.definition["min_num_detected_taps"]
        )
        median_ok = stats["median_ioi"] != 9999
        failed = not (min_responses_ok and median_ok)
        stats = json.dumps(stats, cls=NumpySerializer)
        return {
            "failed": failed,
            "stats": stats,
            "num_resp_onsets_detected": num_resp_onsets_detected,
        }

    def gives_feedback(self, experiment, participant):
        return self.position == 0

    def show_feedback(self, experiment, participant):
        num_resp_onsets_detected = self.analysis["num_resp_onsets_detected"]

        if self.failed:
            return InfoPage(
                Markup(
                    f"""
                    <h4>Your tapping was bad...</h4>
                    We detected {num_resp_onsets_detected} taps in the recording. This is not sufficient for this task.
                    Please try to do one or more of the following:
                    <ol><li>Tap a steady beat, providing at least 5-10 taps.</li>
                        <li>Make sure your laptop microphone is working and you are not using headphones or earplugs.</li>
                        <li>Tap on the surface of your laptop using your index finger.</li>
                        <li>Make sure you are in a quiet environment (the experiment will not work with noisy recordings).</li>
                    </ol>
                    <b><b>If we cannot detect your tapping signal in the recording, the experiment will terminate.</b></b>
                    """
                ),
                time_estimate=5,
            )
        else:
            return InfoPage(
                Markup(
                    f"""
                    <h4>Good!</h4>
                    We could detect {num_resp_onsets_detected} taps in the recording.
                    """
                ),
                time_estimate=5,
            )


class FreeTappingRecordTest(StaticTrialMaker):
    """
    This pre-screening test is designed to quickly determine whether participants
    are able to provide valid tapping data. The task is also efficient in determining whether
    participants are following the instructions and use hardware
    and software that meets the technical requirements of REPP.
    To make the most out of it, the test should be used at the
    beginning of the experiment, after providing general instructions.
    This test is intended for unconstrained tapping experiments, where no markers are used.
    By default, we start with a warming up exercise where participants can hear their recording.
    We then perform a test with two trials and exclude participants who fail more than once.
    After the first trial, we provide feedback based on the number of detected taps. The only
    exclusion criterion to fail trials is based on the number of detected taps, by default set to
    a minimum of 3 taps. NOTE: this test should be given after a volume and a tapping calibration test.

    Parameters
    ----------

    label : string
        The label for the test, default: "free_tapping_record_test".

    performance_threshold : int
        The performance threshold, default: 0.6.

    duration_rec_sec : float
        Length of the recording, default: 8 sec.

    min_num_detected_taps : float
        Mininum number of detected taps to pass the test, default: 1.

    n_repeat_trials : float
        Number of trials to repeat in the trial maker, default: 0.

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 10.0.

    trial_class :
        Trial class to use.
    """

    def __init__(
        self,
        label="free_tapping_record_test",
        performance_threshold: int = 0.5,
        duration_rec_sec: int = 8,
        min_num_detected_taps: int = 3,
        n_repeat_trials: int = 1,
        time_estimate_per_trial: float = 10.0,
        trial_class=FreeTappingRecordTrial,
    ):
        self.performance_check_type = "performance"
        self.performance_threshold = performance_threshold
        self.give_end_feedback_passed = False
        self.time_estimate_per_trial = time_estimate_per_trial

        nodes = self.get_nodes(duration_rec_sec, min_num_detected_taps)

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=nodes,
            expected_trials_per_participant=len(nodes),
            n_repeat_trials=n_repeat_trials,
            fail_trials_on_participant_performance_check=False,
            check_performance_at_end=True,
        )

    @property
    def introduction(self):
        return join(
            InfoPage(
                Markup(
                    """
                    <h3>Warming up</h3>
                    <hr>
                    We will now warm up with a short tapping exercise. On the next page,
                    please tap a steady beat in any tempo that you like.
                    <br><br>
                    <b><b>Attention:</b></b> Tap with your index finger and only tap on the surface of your laptop.</b></b>
                    <hr>
                    """
                ),
                time_estimate=3,
            ),
            ModularPage(
                "free_record_example",
                Markup(
                    """
                    <h4>Tap a steady beat</h4>
                    """
                ),
                AudioRecordControl(
                    duration=7.0,
                    show_meter=True,
                    controls=False,
                    auto_advance=False,
                    bot_response_media=resources.files("psynet")
                    / "resources/repp/free_tapping_record.wav",
                ),
                time_estimate=5,
                progress_display=ProgressDisplay(
                    stages=[
                        ProgressStage(7, "Recording.. Start tapping!", "red"),
                    ],
                ),
            ),
            wait_while(
                lambda participant: (
                    not participant.assets["free_record_example"].deposited
                ),
                expected_wait=5,
                log_message="Waiting for free_record_example to be deposited",
            ),
            PageMaker(
                lambda participant: ModularPage(
                    "playback",
                    AudioPrompt(
                        participant.assets["free_record_example"],
                        Markup(
                            """
                        <h3>Can you hear your recording?</h3>
                        <hr>
                        If you do not hear your recording, please make sure
                        your laptop microphone is working and you are not using any headphones or wireless devices.<br><br>
                        <b><b>To proceed, we need to be able to record your tapping.</b></b>
                        <hr>
                        """
                        ),
                    ),
                ),
                time_estimate=5,
            ),
            InfoPage(
                Markup(
                    """
                    <h3>Tapping test</h3>
                    <hr>
                    <b><b>Be careful:</b></b> This is a recording test!<br><br>
                    On the next page, we will ask you again to tap a steady beat in any tempo that you like.
                    <br><br>
                    We will test if we can record your tapping signal properly:
                    <b><b>If we cannot record it, the experiment will terminate here.</b></b>
                    <hr>
                    """
                ),
                time_estimate=3,
            ),
        )

    def get_nodes(self, duration_rec_sec: float, min_num_detected_taps: int):
        return [
            StaticNode(
                definition={
                    "duration_rec_sec": duration_rec_sec,
                    "min_num_detected_taps": min_num_detected_taps,
                    "url_audio": "https://s3.amazonaws.com/repp-materials/silence_1s.wav",
                    # Redundant but keeping for back-compatibility
                },
                assets={
                    "stimulus": ExternalAsset(
                        url="https://s3.amazonaws.com/repp-materials/silence_1s.wav",
                    ),
                },
            )
        ]


class RecordMarkersTrial(AudioRecordTrial, StaticTrial):
    def show_trial(self, experiment, participant):
        return ModularPage(
            "markers_test_trial",
            AudioPrompt(
                self.assets["stimulus"],
                Markup(
                    """
                    <h3>Recording test</h3>
                    <hr>
                    <h4>Please remain silent while we play a sound and record it</h4>
                    """
                ),
            ),
            AudioRecordControl(
                duration=self.definition["duration_sec"],
                show_meter=False,
                controls=False,
                auto_advance=False,
                bot_response_media=resources.files("psynet")
                / "resources/repp/markers_test_record.wav",
            ),
            time_estimate=self.time_estimate,
            progress_display=ProgressDisplay(
                # show_bar=False,
                stages=[
                    ProgressStage(11.5, "Recording...", "red"),
                    ProgressStage(
                        0.5,
                        "Click next when you are ready to continue...",
                        "orange",
                        persistent=True,
                    ),
                ],
            ),
        )

    def show_feedback(self, experiment, participant):
        if self.failed:
            return InfoPage(
                Markup(
                    """
                    <h4>The recording quality of your laptop is not good</h4>
                    This may have many reasons. Please try to do one or more of the following:
                    <ol><li>Increase the volumne of your laptop.</li>
                        <li>Make sure your laptop does not use strong noise cancellation or supression technologies (deactivate them now).</li>
                        <li>Make sure you are in a quiet environment (the experiment will not work with noisy recordings).</li>
                        <li>Do not use headphones, earplugs or wireless devices (unplug them now and use only the laptop speakers).</b></li>
                    </ol>
                    We will try more trials, but <b><b>if the recording quality is not sufficiently good, the experiment will terminate.</b></b>
                    """
                ),
                time_estimate=5,
            )
        else:
            return InfoPage(
                Markup(
                    """
                    <h4>The recording quality of your laptop is good</h4>
                    We will try some more trials.
                    To complete the experiment and get the full reward, you will need to have a good recording quality in all trials.
                    """
                ),
                time_estimate=5,
            )

    def gives_feedback(self, experiment, participant):
        return self.position == 0

    def analyze_recording(self, audio_file: str, output_plot: str):
        from repp.analysis import REPPAnalysis
        from repp.config import sms_tapping

        info = {
            "markers_onsets": self.definition["markers_onsets"],
            "stim_shifted_onsets": self.definition["stim_shifted_onsets"],
            "onset_is_played": self.definition["onset_is_played"],
        }

        title_in_graph = "Participant {}".format(self.participant_id)
        analysis = REPPAnalysis(config=sms_tapping)
        output, analysis, is_failed = analysis.do_analysis(
            info, audio_file, title_in_graph, output_plot
        )
        num_markers_detected = int(analysis["num_markers_detected"])
        correct_answer = self.definition["correct_answer"]

        output = json.dumps(output, cls=NumpySerializer)
        analysis = json.dumps(analysis, cls=NumpySerializer)
        return {
            "failed": correct_answer != num_markers_detected,
            "num_detected_markers": num_markers_detected,
            "output": output,
            "analysis": analysis,
        }


class REPPMarkersTest(StaticTrialMaker):
    """
    This markers test is used to determine whether participants are using hardware
    and software that meets the technical requirements of REPP, such as
    malfunctioning speakers or microphones, or the use of strong noise-cancellation
    technologies. To make the most out of it, the markers check should be used at the
    beginning of the experiment, after providing general instructions
    with the technical requirements of the experiment. In each trial, the markers check plays
    a test stimulus with six marker sounds. The stimulus is then recorded
    with the laptop's microphone and analyzed using the REPP's signal processing pipeline.
    During the marker playback time, participants are supposed to remain silent
    (not respond).

    Parameters
    ----------

    label : string
        The label for the markers check, default: "repp_markers_test".

    performance_threshold : int
        The performance threshold, default: 1.

    materials_url: string
        The location of the REPP materials, default: https://s3.amazonaws.com/repp-materials.

    n_trials : int
        The total number of trials to display, default: 3.

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 12.0.

    trial_class :
        The trial class to use, default: RecordMarkersTrial
    """

    def __init__(
        self,
        label="repp_markers_test",
        performance_threshold: int = 0.6,
        materials_url: str = "https://s3.amazonaws.com/repp-materials",
        n_trials: int = 3,
        time_estimate_per_trial: float = 12.0,
        trial_class=RecordMarkersTrial,
    ):
        self.n_trials = n_trials
        self.materials_url = materials_url

        self.give_end_feedback_passed = False
        self.performance_check_type = "performance"
        self.performance_threshold = performance_threshold
        self.time_estimate_per_trial = time_estimate_per_trial

        nodes = self.get_nodes()

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=nodes,
            expected_trials_per_participant=len(nodes),
            check_performance_at_end=True,
            assets={"rules_image": self.image_asset},
        )

    @property
    def image_asset(self):
        return ExternalAsset(
            url=f"{self.materials_url}/REPP-image_rules.png",
        )

    @property
    def introduction(self):
        return PageMaker(
            lambda assets: InfoPage(
                Markup(
                    f"""
            <h3>Recording test</h3>
            <hr>
            Now we will test the recording quality of your laptop. In {self.n_trials} trials, you will be
            asked to remain silent while we play and record a sound.
            <br><br>
            <img style="width:50%" src="{assets["rules_image"].url}"  alt="rules_image">
            <br><br>
            When ready, click <b>next</b> for the recording test and please wait in silence.
            <hr>
            """
                ),
            ),
            time_estimate=5,
        )

    def get_nodes(self):
        return [
            StaticNode(
                definition={
                    "stim_name": f"audio{i + 1}.wav",
                    "markers_onsets": [
                        2000.0,
                        2280.0,
                        2510.0,
                        8550.022675736962,
                        8830.022675736962,
                        9060.022675736962,
                    ],
                    "stim_shifted_onsets": [4500.0, 5000.0, 5500.0],
                    "onset_is_played": [True, True, True],
                    "duration_sec": 12,
                    "correct_answer": 6,
                },
                assets={
                    "stimulus": ExternalAsset(
                        f"{self.materials_url}/audio{i + 1}.wav",
                    )
                },
            )
            for i in range(3)
        ]


class LanguageVocabularyTrial(StaticTrial):
    time_estimate = None

    def finalize_definition(self, definition, experiment, participant):
        indices = range(4)
        definition["order"] = random.sample(indices, len(indices))
        return definition

    def show_trial(self, experiment, participant):
        order = self.definition["order"]
        choices = ["correct", "wrong1", "wrong2", "wrong3"]
        image_urls = [self.assets[f"image_{choice}"].url for choice in choices]

        return ModularPage(
            "language_vocabulary_trial",
            AudioPrompt(
                self.assets["audio"],
                "Select the picture that matches the word that you heard.",
            ),
            PushButtonControl(
                choices=[choices[i] for i in order],
                labels=[
                    f'<img src="{image_urls[i]}" alt="notworking" height="65px" width="65px"/>'
                    for i in order
                ],
                style="min-width: 100px; margin: 10px; background: none; border-color: grey;",
                arrange_vertically=False,
                bot_response="correct",
            ),
        )

    def score_answer(self, answer, definition):
        if answer == "correct":
            return 1
        else:
            return 0


class LanguageVocabularyTest(StaticTrialMaker):
    """
    This is a basic language vocabulary test supported in five languages (determined by ``language_code``): American English (en-US), German (de-DE), Hindi (hi-IN),
    Brazilian Portuguese (pt-BR), and Spanish (es-ES). In each trial, a spoken word is played in the target
    language and the participant must decide which of the given images in the choice set match
    the spoked word, from a total of four possible images. The materials are the same for all languages.
    The trials are randomly selected from a total pool of 14 trials.

    Parameters
    ----------

    label : string
        The label for the language vocabulary test, default: "language_vocabulary_test".

    language_code : string
        The language code of the target language for the test (en-US, de-DE, hi-IN, pt-BR,sp-SP), default: "en-US".

    media_url:
        Location of the test materials, default: "https://s3.amazonaws.com/langauge-test-materials"

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 5.0.

    performance_threshold : int
        The performance threshold, default: 6.

    n_trials : float
        The total number of trials to display, default: 7.

    trial_class :
        Trial class to use, default: LanguageVocabularyTrial
    """

    def __init__(
        self,
        label="language_vocabulary_test",
        language_code: str = "en-US",
        media_url: str = "https://s3.amazonaws.com/langauge-test-materials",
        time_estimate_per_trial: float = 5.0,
        performance_threshold: int = 6,
        n_trials: int = 7,
        trial_class=LanguageVocabularyTrial,
    ):
        self.media_url = media_url
        self.time_estimate_per_trial = time_estimate_per_trial
        self.performance_threshold = performance_threshold

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=self.get_nodes(media_url, language_code, self.words),
            max_trials_per_participant=n_trials,
            expected_trials_per_participant=n_trials,
            check_performance_at_end=True,
        )

    performance_check_type = "score"

    words = [
        "bell",
        "bird",
        "bow",
        "chair",
        "dog",
        "eye",
        "flower",
        "frog",
        "key",
        "knife",
        "moon",
        "star",
        "sun",
        "turtle",
    ]

    @property
    def introduction(self):
        return join(
            InfoPage(
                Markup(
                    """
                    <h3>Vocabulary test</h3>
                    <p>You will now perform a quick vocabulary test.</p>
                    <p>
                        In each trial, you will hear one word and see 4 pictures.
                        Your task is to match each word with the correct picture.
                    </p>
                    """
                ),
                time_estimate=5,
            ),
        )

    def get_nodes(self, media_url: str, language_code: str, words: list):
        return [
            StaticNode(
                definition={
                    "word": word,
                },
                assets={
                    "audio": ExternalAsset(
                        f"{media_url}/recordings/{language_code}/{word}.wav"
                    ),
                    "image_correct": ExternalAsset(f"{media_url}/images/correct.png"),
                    "image_wrong1": ExternalAsset(f"{media_url}/images/wrong1.png"),
                    "image_wrong2": ExternalAsset(f"{media_url}/images/wrong2.png"),
                    "image_wrong3": ExternalAsset(f"{media_url}/images/wrong3.png"),
                },
            )
            for word in words
        ]


class LextaleTrial(StaticTrial):
    time_estimate = 2.0
    hide_after = 1.0

    def show_trial(self, experiment, participant):
        return ModularPage(
            "lextale_trial",
            ImagePrompt(
                self.assets["word"].url,
                "Does this word exist?",
                width="auto",
                height="100px",
                hide_after=self.hide_after,
                margin_bottom="15px",
                text_align="center",
            ),
            PushButtonControl(
                ["yes", "no"],
                ["yes", "no"],
                arrange_vertically=False,
                style="min-width: 150px; margin: 10px",
            ),
            bot_response=lambda: self.definition["correct_answer"],
        )

    def score_answer(self, answer, definition):
        if answer == definition["correct_answer"]:
            return 1
        else:
            return 0


class LexTaleTest(StaticTrialMaker):
    """
    This is an adapted version (shorter) of the  original LexTale test, which checks participants' English proficiency
    in a lexical decision task: "Lemhöfer, K., & Broersma, M. (2012). Introducing LexTALE: A quick and valid lexical test
    for advanced learners of English. Behavior research methods, 44(2), 325-343". In each trial, a word is presented
    for a short period of time (determined by ``hide_after``) and the participant must decide whether the word is an existing word in English or
    it does not exist. The words are chosen from the original study, which used and validated highly unfrequent
    words in English to make the task very difficult for non-native English speakers. See the documentation for further details.

    Parameters
    ----------

    label : string
        The label for the LexTale test, default: "lextale_test".

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 2.0.

    performance_threshold : int
        The performance threshold, default: 8.

    media_url: str
        Location of the media resources, default: "https://s3.amazonaws.com/lextale-test-materials"

    hide_after : float
        The time in seconds after the word disappears, default: 1.0.

    n_trials : float
        The total number of trials to display, default: 12.

    trial_class :
        Trial class to use, default: LextaleTrial
    """

    def __init__(
        self,
        label="lextale_test",
        time_estimate_per_trial: float = 2.0,
        performance_threshold: int = 8,
        media_url: str = "https://s3.amazonaws.com/lextale-test-materials",
        hide_after: float = 1,
        n_trials: int = 12,
        trial_class=LextaleTrial,
    ):
        self.hide_after = hide_after
        self.n_trials = n_trials
        self.time_estimate_per_trial = time_estimate_per_trial
        self.performance_threshold = performance_threshold

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=self.get_nodes(media_url),
            expected_trials_per_participant=n_trials,
            max_trials_per_participant=n_trials,
            check_performance_at_end=True,
        )

    performance_check_type = "score"

    @property
    def introduction(self):
        return InfoPage(
            Markup(
                f"""
                <h3>Lexical decision task</h3>
                <p>In each trial, you will be presented with either an existing word in English or a fake word that does not exist.</p>
                <p>
                    <b>Your task is to decide whether the word exists not.</b>
                    <br><br>Each word will disappear in {self.hide_after} seconds and you will see a total of {self.n_trials} words.
                </p>
                """
            ),
            time_estimate=5,
        )

    def get_nodes(self, media_url: str):
        return [
            StaticNode(
                definition={
                    "label": label,
                    "correct_answer": correct_answer,
                    "url": f"{media_url}/lextale-{label}.png",  # Redundant but kept for back-compatibility
                },
                assets={"word": ExternalAsset(f"{media_url}/lextale-{label}.png")},
            )
            for label, correct_answer in [
                ("1", "yes"),
                ("2", "yes"),
                ("3", "yes"),
                ("4", "yes"),
                ("5", "yes"),
                ("6", "yes"),
                ("7", "yes"),
                ("8", "no"),
                ("9", "no"),
                ("10", "no"),
                ("11", "no"),
                ("12", "no"),
            ]
        ]


class AttentionTest(Module):
    """
    This is an attention test aimed to identify and remove participants who are not paying attention or following
    the instructions. The attention test has 2 pages and researchers can choose whether to display the two pages or not,
    and which information to display in each page. Researchers can also choose the conditions to exclude particiapnts (determined by ``fail_on``).

    Parameters
    ----------
    label : string
        The label of the AttentionTest module, default: "attention_test".

    pages : int
        Whether to display only the first or both pages. Possible values: 1 and 2. Default: 2.

    fail_on: str
        The condition for the AttentionTest check to fail.
        Possible values: "attention_test_1", "attention_test_2", "any", "both", and `None`. Here, "any" means both checks have to be passed by the particpant to continue, "both" means one of two checks can fail and the participant can still continue, and `None` means both checks can fail and the participant can still continue. Default: "attention_test_1".

    prompt_1_explanation: str
        The text (including HTML code) to display in the first part of the first paragraph of the first page. Default: "Research on personality has identified characteristic sets of behaviours and cognitive patterns that evolve from biological and enviromental factors. To show that you are paying attention to the experiment, please ignore the question below and select the 'Next' button instead."

    prompt_1_main: str
        The text (including HTML code) to display in the last paragraph of the first page. Default: "As a person, I tend to be competitive, jealous, ambitious, and somewhat impatient."

    prompt_2: str
        The text to display on the second page. Default: "What is your favourite color?".

    attention_test_2_word: str
        The word that the user has to enter on the second page. Default: "attention".

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 5.0.
    """

    def __init__(
        self,
        label: str = "attention_test",
        pages: int = 2,
        fail_on: str = "attention_test_1",
        prompt_1_explanation: str = """
            Research on personality has identified characteristic sets of behaviours and cognitive patterns that
            evolve from biological and enviromental factors. To show that you are paying attention to the experiment,
            please ignore the question below and select the 'Next' button instead.""",
        prompt_1_main: str = "As a person, I tend to be competitive, jealous, ambitious, and somewhat impatient.",
        prompt_2="What is your favourite color?",
        attention_test_2_word="attention",
        time_estimate_per_trial: float = 5.0,
    ):
        assert pages in [1, 2]
        assert not (pages == 1 and fail_on in ["attention_test_2", "both"])
        assert fail_on in [
            "attention_test_1",
            "attention_test_2",
            "any",
            "both",
            None,
        ]

        self.label = label
        self.pages = pages
        self.fail_on = fail_on
        self.attention_test_2_word = attention_test_2_word

        prompt_1_next_page = f""" Also, you must ignore
        the question asked in the next page, and type "{attention_test_2_word}" in the box.
        <br><br>
        {prompt_1_main}"""
        self.prompt_1_text = (
            f"{prompt_1_explanation}{prompt_1_next_page if self.pages == 2 else ''}"
        )
        self.prompt_2 = prompt_2
        self.elts = join(
            ModularPage(
                label="attention_test_1",
                prompt=Markup(f"""{self.prompt_1_text}"""),
                control=RadioButtonControl(
                    [1, 2, 3, 4, 5, 6, 7, 0],
                    [
                        Markup("Completely disagree"),
                        Markup("Strongly disagree"),
                        Markup("Disagree"),
                        Markup("Neutral"),
                        Markup("Agree"),
                        Markup("Strongly agree"),
                        Markup("Completely agree"),
                        Markup("Other"),
                    ],
                    name=self.label,
                    arrange_vertically=True,
                    force_selection=False,
                    show_reset_button="on_selection",
                ),
                time_estimate=time_estimate_per_trial,
                bot_response=lambda: None,
            ),
            conditional(
                "exclude_check_1",
                lambda experiment, participant: (
                    participant.answer is not None
                    and self.fail_on in ["attention_test_1", "any"]
                ),
                UnsuccessfulEndPage(
                    failure_tags=["performance_check", "attention_test_1"]
                ),
            ),
            CodeBlock(
                lambda experiment, participant: participant.var.new(
                    "first_check_passed", participant.answer is None
                )
            ),
            conditional(
                "attention_test_2",
                lambda experiment, participant: self.pages == 2,
                ModularPage(
                    label="attention_test_2",
                    prompt=self.prompt_2,
                    control=TextControl(width="300px"),
                    time_estimate=time_estimate_per_trial,
                    bot_response=lambda: self.attention_test_2_word,
                ),
            ),
            conditional(
                "exclude_check_2",
                lambda experiment, participant: (
                    self.pages == 2
                    and fail_on is not None
                    and participant.answer.lower() != self.attention_test_2_word
                    and (
                        self.fail_on in ["attention_test_2", "any"]
                        or not participant.var.first_check_passed
                    )
                ),
                UnsuccessfulEndPage(
                    failure_tags=["performance_check", "attention_test_2"]
                ),
            ),
        )
        super().__init__(self.label, self.elts)


class ColorBlindnessTrial(StaticTrial):
    def show_trial(self, experiment, participant):
        return ModularPage(
            "color_blindness_trial",
            ImagePrompt(
                self.assets["image"].url,
                _p("color_blindness_test", "Write down the number in the image."),
                width="350px",
                height="344px",
                hide_after=self.trial_maker.hide_after,
                margin_bottom="15px",
                text_align="center",
            ),
            TextControl(width="100px"),
            bot_response=lambda: self.definition["correct_answer"],
        )

    def score_answer(self, answer, definition):
        if answer == definition["correct_answer"]:
            return 1
        else:
            return 0


class ColorBlindnessTest(StaticTrialMaker):
    """
    The color blindness test checks the participant's ability to perceive
    colors. In each trial an image is presented which contains a number and the
    participant must enter the number that is shown into a text box. The image
    disappears after 3 seconds by default, which can be adjusted by providing a different
    value in the ``hide_after`` parameter.

    Parameters
    ----------

    label : string
        The label for the color blindness test, default: "color_blindness_test".

    media_url : string
        The url under which the images to be displayed can be referenced, default:
        "https://s3.amazonaws.com/ishihara-eye-test/jpg"

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 5.0.

    performance_threshold : int
        The performance threshold, default: 4.

    hide_after : float, optional
        The time in seconds after which the image disappears, default: 3.0.

    trial_class :
        Trial class to use, default: ColorBlindnessTrial.
    """

    def __init__(
        self,
        label="color_blindness_test",
        media_url: str = "https://s3.amazonaws.com/ishihara-eye-test/jpg",
        time_estimate_per_trial: float = 5.0,
        performance_threshold: int = 4,
        hide_after: Optional[float] = 3.0,
        trial_class=ColorBlindnessTrial,
    ):
        self.hide_after = hide_after
        self.time_estimate_per_trial = time_estimate_per_trial
        self.performance_threshold = performance_threshold

        nodes = self.get_nodes(media_url)

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=nodes,
            expected_trials_per_participant=len(nodes),
            check_performance_at_end=True,
        )

    performance_check_type = "score"

    @property
    def introduction(self):

        instructions = [
            _p(
                "color_blindness_test_intro_1",
                "We will now perform a quick test to check your ability to perceive colors.",
            ),
            _p(
                "color_blindness_test_intro_1",
                "In each trial, you will be presented with an image that contains a number.",
            ),
        ]

        if self.hide_after is not None:
            instructions.append(
                _p(
                    "color_blindness_test_intro_1",
                    "This image will disappear after {HIDE_AFTER} seconds.",
                ).format(HIDE_AFTER=self.hide_after)
            )
        instructions.append(
            _p(
                "color_blindness_test_intro_1",
                "You must enter the number that you see into the text box.",
            )
        )
        return InfoPage(
            " ".join(instructions),
            time_estimate=10,
        )

    def get_nodes(self, media_url: str):
        return [
            StaticNode(
                definition={
                    "label": label,
                    "correct_answer": answer,
                },
                assets={
                    "image": ExternalAsset(
                        url=f"{media_url}/ishihara-{label}.jpg",
                    )
                },
            )
            for label, answer in [
                ("1", "12"),
                ("2", "8"),
                ("3", "29"),
                ("4", "5"),
                ("5", "3"),
                ("6", "15"),
            ]
        ]


class ColorVocabularyTrial(StaticTrial):
    def show_trial(self, experiment, participant):
        return ModularPage(
            "color_vocabulary_trial",
            ColorPrompt(
                self.definition["target_hsl"],
                "Which color is shown in the box?",
                text_align="center",
            ),
            PushButtonControl(
                self.definition["choices"],
                arrange_vertically=False,
                style="min-width: 150px; margin: 10px",
            ),
            bot_response=lambda: self.definition["correct_answer"],
        )

    def score_answer(self, answer, definition):
        if answer == definition["correct_answer"]:
            return 1
        else:
            return 0


class ColorVocabularyTest(StaticTrialMaker):
    """
    The color vocabulary test checks the participant's ability to name colors. In each trial, a
    colored box is presented and the participant must choose from a set of colors which color is
    displayed in the box. The colors which are presented can be freely chosen by providing an
    optional ``colors`` parameter. See the documentation for further details.

    Parameters
    ----------

    label : string
        The label for the color vocabulary test, default: "color_vocabulary_test".

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 5.0.

    performance_threshold : int
        The performance threshold, default: 4.

    colors : list, optional
        A list of tuples each representing one color option. The tuples are of
        the form ("color-name", [H, S, L]) corresponding to hue, saturation, and lightness.
        Hue takes integer values in [0-360]; saturation and lightness take integer values in [0-100].
        Default: the list of the six colors "turquoise", "magenta", "granite", "ivory", "maroon", and "navy".

    trial_class :
        Trial class to use, default: ColorBlindnessTrial.
    """

    def __init__(
        self,
        label="color_vocabulary_test",
        time_estimate_per_trial: float = 5.0,
        performance_threshold: int = 4,
        colors: Optional[list] = None,
        trial_class=ColorVocabularyTrial,
    ):
        if colors:
            self.colors = colors
        self.performance_threshold = performance_threshold
        self.time_estimate_per_trial = time_estimate_per_trial

        nodes = self.get_nodes(self.colors)

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=nodes,
            expected_trials_per_participant=len(nodes),
            check_performance_at_end=True,
        )

    performance_check_type = "score"

    colors = [
        ("turquoise", [174, 72, 56]),
        ("magenta", [300, 100, 50]),
        ("granite", [0, 0, 40]),
        ("ivory", [60, 100, 97]),
        ("maroon", [0, 100, 25]),
        ("navy", [240, 100, 25]),
    ]

    @property
    def introduction(self):
        return InfoPage(
            Markup(
                """
            <p>We will now perform a quick test to check your ability to name colors.</p>
            <p>
                In each trial, you will be presented with a colored box.
                You must choose which color you see in the box.
            </p>
            """
            ),
            time_estimate=10,
        )

    def get_nodes(self, colors: list):
        stimuli = []
        words = [x[0] for x in colors]
        for correct_answer, hsl in colors:
            choices = words.copy()
            # Todo - think carefully about whether it's a good idea to have random
            # functions inside get_nodes
            random.shuffle(choices)
            definition = {
                "target_hsl": hsl,
                "choices": choices,
                "correct_answer": correct_answer,
            }
            stimuli.append(StaticNode(definition=definition))
        return stimuli


class HeadphoneTrial(StaticTrial):
    prompt_text = None
    test_name = None
    submit_early = False

    def get_prompt(self):
        assert self.prompt_text is not None
        return AudioPrompt(
            self.assets["stimulus"],
            self.prompt_text,
        )

    def show_trial(self, experiment, participant):
        events = {
            "responseEnable": Event(is_triggered_by="promptEnd"),
        }
        if not self.submit_early:
            events["submitEnable"] = Event(is_triggered_by="promptEnd")

        return ModularPage(
            "headphone_trial",
            self.get_prompt(),
            PushButtonControl(["1", "2", "3"]),
            events=events,
            bot_response=lambda bot: self.get_bot_response(bot),
        )

    def get_bot_response(self, bot: Bot):
        is_good_bot = bot.var.get("is_good_bot", default=True)
        correct_answer = self.definition["correct_answer"]
        if is_good_bot:
            return correct_answer
        else:
            wrong_answers = ["1", "2", "3"]
            wrong_answers.remove(correct_answer)
            return random.choice(wrong_answers)

    @property
    def task_description(self):
        raise NotImplementedError()

    @staticmethod
    def get_test_definition():
        raise NotImplementedError()

    def score_answer(self, answer, definition):
        if answer == definition["correct_answer"]:
            return 1
        else:
            return 0


class HeadphoneTest(StaticTrialMaker):
    """
        DISCONTINUED - use HugginsHeadphoneTest, AntiphaseHeadphoneTest, BeepHeadphoneTest instead;
        HugginsHeadphoneTest is recommended.

    The headphone test makes sure that the participant is wearing headphones.
    """

    def __init__(
        self,
        label="headphone_test",
        media_url: Optional[str] = None,
        time_estimate_per_trial: float = 7.5,
        performance_threshold: int = 4,
        n_trials: int = 6,
    ):
        raise NotImplementedError(
            (
                "DISCONTINUED - use HugginsHeadphoneTest, AntiphaseHeadphoneTest, BeepHeadphoneTest instead; "
                "HugginsHeadphoneTest is recommended."
            )
        )


class GeneralHeadphoneTest(StaticTrialMaker):
    """
        DISCONTINUED - use HugginsHeadphoneTest or AntiphaseHeadphoneTest instead; HugginsHeadphoneTest is recommended.

    The headphone test makes sure that the participant is wearing headphones. In each trial,
    three sounds separated by silences are played and the participant's must judge which sound
    was the softest (quietest). See the documentation for further details.

    Parameters
    ----------

    label : string
        The label for the color headphone check, default: "headphone_test".

    trial_class :
        Trial class to use, recommended HugginsHeadphoneTrial.

    media_url : string
        The url under which the images to be displayed can be referenced, default:
        "https://s3.amazonaws.com/headphone-check".

    time_estimate_per_trial : float
        The time estimate in seconds per trial, default: 7.5.

    performance_threshold : int
        The performance threshold, default: 4.


    """

    def __init__(
        self,
        label,
        media_url: Optional[str] = None,
        time_estimate_per_trial: float = 7.5,
        performance_threshold: int = 4,
        n_trials: int = 6,
    ):
        if media_url is None:
            assert self.test_name is not None
            media_url = f"https://s3.amazonaws.com/headphone-check/{self.test_name}"
        self.time_estimate_per_trial = time_estimate_per_trial
        self.performance_threshold = performance_threshold

        super().__init__(
            id_=label,
            trial_class=self.get_trial_class(),
            nodes=self.get_nodes(media_url),
            check_performance_at_end=True,
            expected_trials_per_participant=n_trials,
            max_trials_per_participant=n_trials,
        )

    performance_check_type = "score"

    @property
    def test_name(self):
        raise NotImplementedError()

    @property
    def test_definition(self):
        raise NotImplementedError()

    @property
    def task_description(self):
        raise NotImplementedError()

    @property
    def introduction(self):
        return InfoPage(
            Markup(
                f"""
            <p>We will now perform a quick test to check that you are wearing headphones.</p>
            <p>
                In each trial, you will hear three sounds separated by silences.
                {self.task_description}
            </p>
            """
            ),
            time_estimate=10,
        )

    def get_trial_class(self, node=None, participant=None, experiment=None):
        raise NotImplementedError()

    def get_nodes(self, media_url: str):
        return [
            StaticNode(
                definition={
                    "label": label,
                    "correct_answer": answer,
                },
                assets={
                    "stimulus": ExternalAsset(
                        join_path(media_url, f"{label}.wav"),
                    )
                },
            )
            for label, answer in self.test_definition
        ]


class HugginsHeadphoneTrial(HeadphoneTrial):
    prompt_text = "Which noise contains the hidden beep -- 1, 2, or 3?"
    test_name = "huggins"


class HugginsHeadphoneTest(GeneralHeadphoneTest):
    """
    Implements: Milne, A.E., Bianco, R., Poole, K.C. et al. An online headphone screening test based on dichotic pitch.
    Behav Res 53, 1551–1562 (2021). https://doi.org/10.3758/s13428-020-01514-0
    """

    def __init__(
        self,
        label="huggins_headphone_test",
        media_url: Optional[str] = None,
        time_estimate_per_trial: float = 7.5,
        performance_threshold: int = 4,
        n_trials: int = 6,
    ):
        super().__init__(
            label, media_url, time_estimate_per_trial, performance_threshold, n_trials
        )

    @property
    def test_name(self):
        return "huggins"

    @property
    def test_definition(self):
        return [
            (f"HugginsPitch_set{set_id}_{sound_position}", f"{sound_position}")
            for set_id in range(1, 7)
            for sound_position in range(1, 4)
        ]

    @property
    def task_description(self):
        return (
            "One of the noises has a faint beep hidden within. "
            "Your task will be to judge <strong> which sound had the beep.</strong>"
        )

    def get_trial_class(self, node=None, participant=None, experiment=None):
        return HugginsHeadphoneTrial


class AntiphaseHeadphoneTrial(HeadphoneTrial):
    prompt_text = "Which sound was softest (quietest) -- 1, 2, or 3?"
    test_name = "antiphase"


class AntiphaseHeadphoneTest(GeneralHeadphoneTest):
    """
    Implements: Woods, K. J. P., Siegel, M. H., Traer, J., & McDermott, J. H. (2017). Headphone screening to facilitate
    web-based auditory experiments. Attention, perception & psychophysics, 79(7), 2064–2072.
    https://doi.org/10.3758/s13414-017-1361-2

    Note: we currently recommend using the HugginsHeadphoneTest instead.
    """

    def __init__(
        self,
        label="antiphase_headphone_test",
        media_url: Optional[str] = None,
        time_estimate_per_trial: float = 7.5,
        performance_threshold: int = 4,
        n_trials: int = 6,
    ):
        super().__init__(
            label, media_url, time_estimate_per_trial, performance_threshold, n_trials
        )

    @property
    def test_name(self):
        return "antiphase"

    @property
    def test_definition(self):
        return [
            ("antiphase_HC_ISO", "2"),
            ("antiphase_HC_IOS", "3"),
            ("antiphase_HC_SOI", "1"),
            ("antiphase_HC_SIO", "1"),
            ("antiphase_HC_OSI", "2"),
            ("antiphase_HC_OIS", "3"),
        ]

    @property
    def task_description(self):
        return "Your task will be to judge <strong> which sound was the softest (quietest).</strong>"

    def get_trial_class(self, node=None, participant=None, experiment=None):
        return AntiphaseHeadphoneTrial


class BeepHeadphoneTrial(HeadphoneTrial):
    prompt_text = _p(
        "Beep-headphone-test",
        "Which sound is different from the other two: 1, 2, or 3?",
    )
    test_name = "beep"


class BeepHeadphoneTest(GeneralHeadphoneTest):
    def __init__(
        self,
        label="beep_headphone_test",
        media_url: Optional[str] = None,
        time_estimate_per_trial: float = 7.5,
        performance_threshold: int = 4,
        n_trials: int = 6,
    ):
        super().__init__(
            label, media_url, time_estimate_per_trial, performance_threshold, n_trials
        )

    @property
    def test_name(self):
        return "beep_headphone_test"

    @property
    def test_definition(self):
        return [
            ("3444", "1"),
            ("3445", "2"),
            ("3446", "3"),
            ("3444", "1"),
            ("3445", "2"),
            ("3446", "3"),
        ]

    @property
    def task_description(self):
        return _(
            "Your task will be to judge <strong>which sound is the odd one out</strong>."
        )

    def get_trial_class(self, node=None, participant=None, experiment=None):
        return BeepHeadphoneTrial


class AudioForcedChoiceTrial(StaticTrial):
    def show_trial(self, experiment, participant):
        return ModularPage(
            "audio_forced_choice_trial",
            AudioPrompt(
                self.assets["stimulus"],
                self.definition["question"],
            ),
            PushButtonControl(self.definition["answer_options"]),
            bot_response=self.definition["answer"],
        )

    def score_answer(self, answer, definition):
        if answer == definition["answer"]:
            return 1
        else:
            return 0


class AudioForcedChoiceTest(StaticTrialMaker):
    """
    The audio forced choice test makes sure that the participant can correctly classify a sound.
    In each trial, the participant hears one sound and has to pick one answer from a list.
    Some use-cases where this test can be of use:
    - You only have a few stimuli with ground truth annotation and want the participant to annotate the rest. You can
      use the test to make sure that the participant is capable to classify the stimuli correctly.
    - You implemented an experiment that assumes participants are able to classify sounds (e.g., which bird sings the
      played bird song)
    - During the main experiment, participants record themselves reading a sentence. There can be issues with the
      recording e.g., the participant misreads the sentence. Familiarizing the participants with these kind of errors
      beforehand can raise awareness of these issues. Furthermore, participants can be under the impression that their
      own recordings are being rated by others, which might increase motivation to do the task properly.


    Parameters
    ----------

    csv_path :
        The path to a valid csv file with headers. The file must contain the two columns `url` and `answer`.

    answer_options :
        List of answer options.

    instructions :
        Text of initial instruction page.

    question :
        Question asked at every trial of the test. If the table already contains a column `question` this value will be
        taken.

    performance_threshold :
        The performance threshold. The amount of mistakes the participant is allowed to make before failing the
        performance check.

    label :
        The label for the audio forced choice check, default: "audio_forced_choice_test".

    time_estimate_per_trial :
        The time estimate in seconds per trial, default: 8.

    n_stimuli_to_use :
        If None, all stimuli are used (default). If integer is supplied, n random stimuli are taken.

    specific_stimuli :
        If None, all stimuli are used (default). If list of indexes is supplied, only indexes are used.

    trial_class :
        Trial class to use, default: AudioForcedChoiceTrial.
    """

    def __init__(
        self,
        csv_path: str,
        answer_options: list,
        instructions: str,
        question: str,
        performance_threshold: int,
        label="audio_forced_choice_test",
        time_estimate_per_trial: float = 8.0,
        n_stimuli_to_use: Optional[int] = None,
        specific_stimuli: Optional[List] = None,
        trial_class=AudioForcedChoiceTrial,
    ):
        assert not (specific_stimuli is not None and n_stimuli_to_use is not None)

        self.answer_options = answer_options
        stimuli = self.load_stimuli(csv_path, question)

        self._instructions = instructions

        self.n_stimuli_to_use = n_stimuli_to_use

        self.check_stimuli(stimuli, specific_stimuli)

        self.time_estimate_per_trial = time_estimate_per_trial
        self.performance_threshold = performance_threshold

        nodes = self.get_nodes(label, stimuli, specific_stimuli)

        num_trials = n_stimuli_to_use if n_stimuli_to_use else len(nodes)

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=nodes,
            check_performance_at_end=True,
            expected_trials_per_participant=num_trials,
            max_trials_per_participant=num_trials,
        )

    performance_check_type = "score"

    def load_stimuli(self, csv_path, question):
        import pandas as pd

        assert file_exists(csv_path)

        df = pd.read_csv(csv_path)
        columns = list(df.columns)

        assert "url" in columns
        assert "answer" in columns

        stimuli = []
        for index, row in df.iterrows():
            stimulus = dict(row)
            assert stimulus["url"].startswith("http")  # Make sure url starts with http
            stimulus["answer_options"] = self.answer_options
            if "question" not in columns:
                stimulus["question"] = question
            stimuli.append(stimulus)
        return stimuli

    def check_stimuli(self, stimuli, specific_stimuli):
        used_answer_options = list(set([s["answer"] for s in stimuli]))

        # Make sure that all answer options in the file are also selectable during the experiment
        assert all([answer in self.answer_options for answer in used_answer_options])

        if specific_stimuli is not None:
            # Make sure all indexes are valid (i.e., are integers, go from 0 to max id)
            assert all([isinstance(i, int) for i in specific_stimuli])
            assert min(specific_stimuli) >= 0
            assert max(specific_stimuli) < len(stimuli)

        if self.n_stimuli_to_use is not None:
            assert self.n_stimuli_to_use <= len(
                stimuli
            )  # Cannot select more stimuli than which are available
            assert self.n_stimuli_to_use > 0  # Must be an integer larger than 0

    @property
    def introduction(self):
        return InfoPage(
            Markup(self._instructions),
            time_estimate=10,
        )

    def get_nodes(self, label, stimuli, specific_stimuli):
        if self.n_stimuli_to_use is not None:
            shuffle(stimuli)
            stimuli = stimuli[: self.n_stimuli_to_use]

        elif specific_stimuli is not None:
            stimuli = [stimuli[i] for i in specific_stimuli]

        return [
            StaticNode(
                definition=stimulus,
                assets={
                    "stimulus": ExternalAsset(
                        url=stimulus["url"],
                    )
                },
            )
            for i, stimulus in enumerate(stimuli)
        ]
