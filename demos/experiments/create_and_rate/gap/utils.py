from markupsafe import Markup

from psynet.modular_page import AudioMeterControl, AudioPrompt, ModularPage
from psynet.page import InfoPage
from psynet.prescreen import HugginsHeadphoneTest
from psynet.timeline import join, switch


def get_instructions():
    return join(
        switch(
            lambda experiment, participant: participant.var.is_rater,
            {
                # Creator
                False: join(
                    InfoPage(
                        Markup(
                            """
                            Welcome to the experiment! <br>
                            In this experiment, you will hear a short spoken sentence.
                            You will be asked to put yourself in the situation this recording could occur and then
                            record yourself reading the same sentence.<br><br>
                            This task should be done in a quiet environment using headphones.<br>
                            In the next page, we will test your microphone.
                        """
                        ),
                        time_estimate=5,
                    ),
                    ModularPage(
                        "record_calibrate",
                        Markup(
                            """
                            Now let's check if your microphone is working. Please speak into your microphone and
                            check that the sound is registered properly. If the sound is too quiet, try moving your
                            microphone closer or increasing the input volume on your computer. <br><br>
                            In the next page, we will ask you questions to determine whether you are a native English speaker.
                        """
                        ),
                        AudioMeterControl(),
                        time_estimate=5,
                    ),
                ),
                # Rater
                True: InfoPage(
                    Markup(
                        """
                        Welcome to the experiment! <br>
                        In this experiment, you will listen to different recordings of a sentence.
            You will listen to multiple recordings in a row and need to select the recording, you perceive as most
            emotional.<br><br>
            This task should be done in a quiet environment using headphones.<br>
            In the next page, we will ask you questions to determine whether you are a native English speaker.
            """
                    ),
                    time_estimate=5,
                ),
            },
        ),
        #######################
        # Prescreens
        #######################
        InfoPage(
            "Now let's check if your headphones are working properly", time_estimate=3
        ),
        ModularPage(
            "volume_adjust",
            AudioPrompt(
                "https://headphone-check.s3.amazonaws.com/funk_game_loop.wav",
                "Do you hear a funky tune? Please adjust your volume to a comfortable level",
            ),
            time_estimate=3,
        ),
        HugginsHeadphoneTest(),
        #######################
        # Instructions before practice + specific prescreen for creator
        #######################
        switch(
            lambda experiment, participant: participant.var.is_rater,
            {
                # Creator
                False: join(
                    InfoPage(
                        Markup(
                            """
                    Well done! Now let's get started with the main experiment. <br>
                    In this experiment, you will be asked to put yourself in the situation a recording could occur and
                    then record yourself reading the same sentence.<br><br>

                    Each recording session consists of three pages. On the first page, you will listen to a recording of a
                    sentence. You can listen to this recording as often as you like. When listening, think about the
                    situation in which this recording could occur.<br><br>
                    Press "Next", to read the instructions for the second page of the recording session.
                    """
                        ),
                        time_estimate=10,
                    ),
                    InfoPage(
                        Markup(
                            """
                        The second page of the recording session consists of:
                        <ol>
                            <li>Listening to the same recording you previously listened to (indicated by the orange).
                            Recall the situation in which this recording could occur.</li>
                            <li>Put yourself in this situation and read the sentence as if you were in the situation (indicated
                            by red bar)</li>
                            <li>Listen to your own recording (indicated by blue bar)</li>
                        </ol>
                        You will automatically move to another page. Press "Next", to read the instructions for the third
                        and last page of the recording session.
                        """
                        ),
                        time_estimate=5,
                    ),
                    InfoPage(
                        Markup(
                            """
                        On the last page of the recording session, you have to verify that your own recording is correct.
                        Select from the following options:
                        <ul>
                            <li><span class="badge bg-danger">My own recording is bad</span> – pick this option if your
                            own recording was bad, or</li>
                            <li><span class="badge bg-success">My own recording is correct</span> – pick if your own
                            recording is good</li>
                        </ul>
                        """
                        ),
                        time_estimate=5,
                    ),
                    InfoPage(
                        Markup(
                            """
                        <strong>During the experiment, make sure you:</strong><br>
                        <ol>
                        <li>Listen in silence during the listening phase</li>
                        <li>Repeat the sentence only once</li>
                        <li>Think about the situation in which this recording could occur</li>
                        <li>Record the sentence as if you were in the situation</li>
                        </ol><br>
                    """
                        ),
                        time_estimate=5,
                    ),
                ),
                # Rater
                True: join(
                    InfoPage(
                        Markup(
                            """
                    Well done! Now let's get started with the main experiment. <br>
                    In this experiment, you will be presented with different recordings of a sentence. You have to select
                    the recording, which sounds most emotional to you.
                    """
                        ),
                        time_estimate=5,
                    ),
                ),
            },
            fix_time_credit=False,
        ),
    )
