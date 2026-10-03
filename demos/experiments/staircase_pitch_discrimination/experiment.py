import random

import numpy as np
import soundfile as sf
from dominate import tags

import psynet.experiment
from psynet.asset import OnDemandAsset
from psynet.bot import Bot
from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import Event, Timeline
from psynet.trial.staircase import (
    GeometricStaircaseChain,
    GeometricStaircaseNode,
    GeometricStaircaseTrial,
    GeometricStaircaseTrialMaker,
)

# Overview #####################################################################

# This experiment implements a pitch discrimination task. In each trial, the participant
# hears two tones, one after the other. They must identify which tone was higher in pitch.
# The difficulty of the task is adjusted using a 2-up 1-down staircase procedure.
# In a 2-up 1-down procedure, the difficulty is increased after two correct responses,
# and conversely decreased after one incorrect response.

# The task has two parameters: the amplitude of the tones, and the duration of the tones.
# The task is administered in a series of chains, each with a different combination of
# amplitude and duration.

# Hyperparameters #############################################################

n_chains_per_condition = 2

# The experiment has 4 conditions, defined by the following combinations of amplitude and duration:
# - Amplitude 0.5, duration 0.5
# - Amplitude 0.5, duration 1.0
# - Amplitude 1.0, duration 0.5
# - Amplitude 1.0, duration 1.0
# Each condition has n_chains_per_condition chains.
chain_definitions = [
    {
        "tone_duration": duration,
        "tone_amplitude": amplitude,
    }
    for amplitude in [0.5, 1.0]
    for duration in [0.5, 1.0]
    for _ in range(n_chains_per_condition)
]

n_chains = len(chain_definitions)
chain_length = 15

# #############################################################################


def get_start_nodes(participant):
    return [
        PitchDiscriminationNode(
            parameter=1.0,
            context=chain_definition,
            # In a future PsyNet version, we would like the user instead to specify a list of chains here;
            # then we could get rid of the term 'context', as it would be clear that these parameters are scoped
            # to the chain, not to the node/trial.
        )
        for chain_definition in chain_definitions
    ]


# When implementing a staircase procedure, we need to define a subclass of GeometricStaircaseNode.
# This class will define how the difficulty of the task is adjusted in response to the participant's responses.
class PitchDiscriminationNode(GeometricStaircaseNode):
    # The GeometricStaircase implementation supports a k-up, 1-down procedure.
    # In this case, we are using a 2-up, 1-down procedure.
    k = 2

    # The step parameter determines how much the difficulty level changes after each reversal.
    step = 0.5

    def increase_difficulty(self, parameter):
        # Smaller pitch differences are harder
        return parameter * self.step

    def decrease_difficulty(self, parameter):
        # Larger pitch differences are easier
        max_value = 12  # semitones
        return min(max_value, parameter / self.step)


# We also need to define a subclass of GeometricStaircaseTrial.
# This determines how the task is presented to the participant.
class PitchDiscriminationTrial(GeometricStaircaseTrial):
    time_estimate = 5

    sample_rate = 44100
    tone_duration = 1.0
    silence_duration = 0.5
    rise_time = 0.25

    # The finalize_definition method is called when the trial is created.
    # It is used to determine various stimulus parameters, such as the pitches of the tones.
    # It also cues the creation of any assets (e.g. audio files) that will be needed to present the trial.
    def finalize_definition(self, definition, experiment, participant):
        parameter = definition["parameter"]
        correct_answer = random.choice(["First", "Second"])
        lower_pitch = 60  # MIDI note number
        higher_pitch = lower_pitch + parameter

        # "Which pitch is higher?"
        if correct_answer == "First":
            pitches = [higher_pitch, lower_pitch]
        else:
            pitches = [lower_pitch, higher_pitch]

        frequencies = [self.midi_to_freq(pitch) for pitch in pitches]

        definition.update(
            {
                "correct_answer": correct_answer,
                "pitches": pitches,
                "frequencies": frequencies,
            }
        )

        self.add_assets(
            {
                "stimulus": OnDemandAsset(
                    function=self.synth_stimulus,
                    extension=".wav",
                )
            }
        )

        return definition

    def midi_to_freq(self, midi):
        return 440 * 2 ** ((midi - 69) / 12)

    # For convenience, all values in the `definition` attribute are available as arguments in synth_stimulus.
    # It's also possible to access arbitrary trial properties via ``self``.
    def synth_stimulus(self, path, frequencies):
        # Synthesize two tones one after the other, each of length 1 second,
        # with the specified frequencies
        tone_amplitude = self.context["tone_amplitude"]
        tone_duration = self.context["tone_duration"]

        waveform = np.concatenate(
            [
                self.make_tone(
                    frequencies[0], amplitude=tone_amplitude, duration=tone_duration
                ),
                self.make_silence(duration=self.silence_duration),
                self.make_tone(
                    frequencies[1], amplitude=tone_amplitude, duration=tone_duration
                ),
            ]
        )

        sf.write(path, waveform, self.sample_rate)

    def make_tone(self, frequency, amplitude, duration):
        n_samples = int(duration * self.sample_rate)
        signal = np.sin(2 * np.pi * frequency * np.arange(n_samples) / self.sample_rate)
        envelope = np.ones(len(signal)) * amplitude
        n_rise_samples = round(self.rise_time * self.sample_rate)
        envelope[:n_rise_samples] = np.linspace(
            start=0, stop=amplitude, num=n_rise_samples
        )
        envelope[-n_rise_samples:] = np.linspace(
            start=amplitude, stop=0, num=n_rise_samples
        )
        return signal * envelope

    def make_silence(self, duration):
        n_samples = round(duration * self.sample_rate)
        return np.zeros(n_samples)

    def show_trial(self, experiment, participant):
        return ModularPage(
            "pitch_discrimination_trial",
            AudioPrompt(self.assets["stimulus"], "Which pitch was higher?"),
            PushButtonControl(
                choices=["First", "Second"],
                arrange_vertically=False,
                bot_response=self.get_bot_response,
            ),
            events={
                "responseEnable": Event(is_triggered_by="promptEnd"),
                "submitEnable": Event(is_triggered_by="promptEnd"),
            },
        )

    def show_feedback(self, experiment, participant):
        if self.score == 1:
            content = tags.p("Correct!", style="color: green")
        else:
            content = tags.p("Incorrect.", style="color: red")

        return ModularPage(
            "pitch_discrimination_feedback",
            content,
            events={
                "nextPage": Event(
                    is_triggered_by="submitEnable",
                    delay=0.5,
                    js="psynet.nextPage()",
                ),
            },
            show_next_button=False,
        )

    bot_thresholds = {
        # Discrimination thresholds for each condition;
        # the first value in the tuple is the tone amplitude, the second is the tone duration.
        (0.5, 0.5): 0.125,
        (0.5, 1.0): 0.25,
        (1.0, 0.5): 0.5,
        (1.0, 1.0): 0.75,
    }

    def get_bot_response(self, bot: Bot):
        # We imagine the bot has the discrimination threshold specified below.
        # We suppose they always respond correctly if the stimulus parameter is
        # above the threshold, and always respond incorrectly if it is below.
        # This is unrealistic (normally they would respond by chance if it is below),
        # but it allows us to produce a simpler automated test.

        bot_threshold = self.bot_thresholds[
            (self.context["tone_amplitude"], self.context["tone_duration"])
        ]

        responds_correctly = self.parameter >= bot_threshold
        if responds_correctly:
            return self.definition["correct_answer"]
        else:
            if self.definition["correct_answer"] == "First":
                return "Second"
            else:
                return "First"

    def score_answer(self, answer, definition):
        return int(answer == definition["correct_answer"])


class Exp(psynet.experiment.Experiment):
    label = "Pitch discrimination demo"

    timeline = Timeline(
        InfoPage(
            """
            In each trial you will hear two tones. One will be higher in pitch than the other.
            Your task is to identify which tone is the highest.
            """,
            time_estimate=5,
        ),
        GeometricStaircaseTrialMaker(
            id_="pitch_discrimination",
            trial_class=PitchDiscriminationTrial,
            node_class=PitchDiscriminationNode,
            # The long-term plan is to update this API so that, instead of specifying a list of start_nodes,
            # we instead specify a list of chains. Each chain can then have its own hyperparameters like
            # max_trials_per_run, max_reversals_per_chain, etc. We are waiting on some other PsyNet changes before
            # we can do this though.
            start_nodes=get_start_nodes,
            # Staircase trial makers default to interleave_chains=False, so the participant finishes
            # one chain before starting the next, as is normal in a staircase procedure.
            # chain_order="random" (the default) shuffles the chains; pass chain_order="listed"
            # to follow the order of get_start_nodes instead.
            max_nodes_per_chain=chain_length,
            expected_trials_per_participant=n_chains * chain_length,
            # This parameter is used to determine when to stop automatic recruitment (if active).
            target_n_participants=1,
        ),
    )

    # This part of the code is optional but good practice.
    # It defines an automated test that checks that the experiment logic is working properly.
    def test_check_bot(self, bot: Bot, **kwargs):
        step = PitchDiscriminationNode.step

        chains = GeometricStaircaseChain.query.filter_by(participant_id=bot.id).all()
        chains.sort(key=lambda c: c.head.id)

        for trial in chains[1].all_trials:
            assert trial.id > max([t.id for t in chains[0].all_trials]), (
                "chains 0 and 1 were unexpectedly mixed"
            )

        for chain in chains:
            # Copied out for now because the demo doesn't use the max_reversals logic
            #
            # max_reversals_per_chain = self.timeline.get_trial_maker(
            #     "pitch_discrimination"
            # ).max_reversals_per_chain
            # n_reversals = sum(
            #     [node.reversal for node in chain.all_nodes if node.reversal is not None]
            # )
            # assert n_reversals == chain.head.n_prev_reversals == max_reversals_per_chain

            # We expect that the last few trials should be near the threshold.
            # Here we check the last 4 trials.
            n = 4
            last_n_trials = sorted(chain.all_trials, key=lambda t: t.id)[-n:]
            last_n_parameters = [
                trial.definition["parameter"] for trial in last_n_trials
            ]

            tone_amplitude = chain.context["tone_amplitude"]
            tone_duration = chain.context["tone_duration"]
            bot_threshold = PitchDiscriminationTrial.bot_thresholds[
                (tone_amplitude, tone_duration)
            ]

            for parameter in last_n_parameters:
                assert bot_threshold * step <= parameter <= bot_threshold / step, (
                    f"Procedure did not converge to bot threshold (chain ID = {chain.id}, "
                    f"last_n_parameters = {last_n_parameters}, threshold = {bot_threshold})"
                )

            if chain.mean_reversal_score is not None:
                assert (
                    bot_threshold * step
                    <= chain.mean_reversal_score
                    <= bot_threshold / step
                ), f"Mean reversal score seems incorrect: {chain.mean_reversal_score}"
