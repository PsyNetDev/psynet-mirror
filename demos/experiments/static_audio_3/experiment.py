from markupsafe import Markup

import psynet.experiment
from psynet.asset import asset
from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import get_logger

logger = get_logger()

##########################################################################################
# Stimuli
##########################################################################################

# The following directory path indicates the location of sound files.
# You can place the sound files anywhere on your computer, and
# update this path according to the new location of the files.
INPUT_PATH_DIR = "audio_file/MidiJS_soundfonts/"
MAX_STIMULI_DURATION = 5


file_names = [
    "Harpsichord C4.mp3",
    "Violin C4.mp3",
    "Trumpet C4.mp3",
    "Guitar C4.mp3",
    "Clarinet C4.mp3",
    "Alto sax C4.mp3",
    "Xylophone C4.mp3",
    "Piano C4.mp3",
    "Flute C4.mp3",
]

# In theory, you could compile these file names by listing the files in a directory,
# but beware: if the files are not stored in the experiment directory then file listing
# won't work once the app is deployed. For now it is best to hard-code the names into
# experiment.py, or alternatively create a manifest JSON file that lists the files that
# the experiment expects to see. We expect to update this functionality in the future to make it more streamlined.
# from os import listdir
# from os.path import isfile, join
# file_names = [f for f in listdir(INPUT_PATH_DIR) if isfile(join(INPUT_PATH_DIR, f))]

nodes = [
    StaticNode(
        definition={"name": file_name},
        assets={"stimulus": asset(INPUT_PATH_DIR + file_name)},
    )
    for file_name in file_names
]


class SoundRatingTrial(StaticTrial):
    time_estimate = MAX_STIMULI_DURATION

    def show_trial(self, experiment, participant):
        return ModularPage(
            "sound_rating",
            AudioPrompt(self.assets["stimulus"], "How much did you like the sound?"),
            PushButtonControl(
                choices=["1", "2", "3", "4", "5"],
                labels=[
                    "I didn't like it at all",
                    "I didn't like it",
                    "It was OK",
                    "I liked it",
                    "I liked it very much",
                ],
                arrange_vertically=False,
            ),
            time_estimate=self.time_estimate,
        )


##########################################################################################
# Experiment
##########################################################################################


class Exp(psynet.experiment.Experiment):
    label = "Static audio demo (3)"

    timeline = Timeline(
        InfoPage(
            Markup(
                """
                On every page, you will hear a short sound.
                Please indicate how much you like the sound on a 5-point scale.
                <br><br>
                <div class="alert alert-warning" role="alert">
                    If the recording does not play after a few seconds, try reloading the page
                    </div>
                """
            ),
            time_estimate=5,
        ),
        StaticTrialMaker(
            id_="static_audio_3",
            trial_class=SoundRatingTrial,
            nodes=nodes,
            target_n_participants=0,
            recruit_mode="n_participants",
            expected_trials_per_participant=len(nodes),
            allow_repeated_nodes=False,
            # Each answer shows the next sound straight away, on the same page.
            prepare_trials_in_advance=True,
        ),
    )
