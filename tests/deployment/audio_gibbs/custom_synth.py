# Note: parselmouth must be installed with pip install praat-parselmouth.
# synth_stimulus is the entry point called by the Audio Gibbs sampler;
# it delegates to synth_batch, which does the parselmouth/Praat synthesis.

import os

import numpy as np

TIMESTAMPS = [0.0, 0.071, 0.142, 0.213, 0.284, 0.355, 0.426]


def synth_stimulus(vector, output_path, chain_definition=None):
    """
    Synthesises a stimulus.

    Parameters
    ----------

    vector : list
        A vector of parameters as produced by the Gibbs sampler,
        for example:

        ::

            [144.11735609, 159.17558762, 232.15967799, 298.43893329, 348.34553954]

    output_path : str
        The output path for the generated file.

    chain_definition
        The chain's definition object.
    """
    times = np.array(TIMESTAMPS)
    assert len(vector) == len(times)
    freqs = np.array(vector)
    x = np.column_stack((times, freqs))

    effects = [{"name": "fade-out", "duration": 0.01}]

    synth_batch(
        [x],
        [output_path],
        "synth_files/audio/norm_stim_vraiment_interro.wav",
        effects=effects,
    )


def synth_batch(
    BPFs,
    filenames,
    baseline_audio_path,
    prepend_path=None,
    append_path=None,
    reference_tone=235,
    man_step_size=0.01,
    man_min_F0=75,
    man_max_F0=600,
    effects=[],
):
    """
    Create stimuli based on BPFs

    Parameters:
    BPFs (list): List of numpy matrices the first column is time, the second column pitch change in cents
    filenames (list): Filenames of synthesized files
    baseline_audio_path (str): Filepath to baseline

    prepend_path (str): name of the wav file to prepend to the audio
    append_path (str): name of the wav file to append to the audio
    reference_tone (int): default 235 Hz
    man_step_size (float): The pitch tracking window size
    man_min_F0 (float): The pitch floor
    man_max_F0 (float): The pitch ceiling

    effects (list): List of dictionaries that describe effects applied to the baseline_audio_path

    """

    from parselmouth import Sound
    from parselmouth.praat import call
    from scipy.io.wavfile import write as write_wav

    # Do some checks
    supported_effects = ["fade-out"]
    if not all(
        ["name" in e.keys() and e["name"] in supported_effects for e in effects]
    ):
        raise ValueError(
            "Your effect must have a name. Currently we only support the following effects: %s"
            % ", ".join(supported_effects)
        )

    if len(BPFs) != len(filenames):
        raise ValueError("Need to be of same length!")

    if append_path is not None and not os.path.exists(append_path):
        raise FileNotFoundError("Specified `append_path` not found on this system")

    if prepend_path is not None and not os.path.exists(prepend_path):
        raise FileNotFoundError("Specified `prepend_path` not found on this system")

    if not os.path.exists(baseline_audio_path):
        raise FileNotFoundError(
            "Specified `baseline_audio_path` not found on this system"
        )

    def cent2herz(ct, base=reference_tone):
        """Converts deviation in cents to a value in Hertz"""
        st = ct / 100
        semi1 = np.log(np.power(2, 1 / 12))
        return np.exp(st * semi1) * base

    # Load the sound
    sound = Sound(baseline_audio_path)
    if prepend_path is not None:
        pre_sound = Sound(prepend_path)

    if append_path is not None:
        app_sound = Sound(append_path)

    # Create a manipulation object
    manipulation = call(sound, "To Manipulation", man_step_size, man_min_F0, man_max_F0)

    # Extract the pitch tier
    pitch_tier = call(manipulation, "Extract pitch tier")

    for BPF_idx, BPF in enumerate(BPFs):
        # Make sure the pitch Tier is empty
        call(pitch_tier, "Remove points between", sound.xmin, sound.xmax)

        # Convert cents to Hertz
        BPF[:, 1] = [cent2herz(ct) for ct in BPF[:, 1]]

        # Populate the pitch tier
        for point_idx in range(BPF.shape[0]):
            call(pitch_tier, "Add point", BPF[point_idx, 0], BPF[point_idx, 1])

        # Use it in the manipulation object
        call([pitch_tier, manipulation], "Replace pitch tier")

        # Synthesize it
        synth_main = call(manipulation, "Get resynthesis (overlap-add)")

        # Assuming all effects are applied to the main file
        for effect in effects:
            if effect["name"] == "fade-out":
                if "duration" in effect.keys():
                    call(
                        synth_main,
                        "Fade out",
                        1,
                        synth_main.xmax - effect["duration"],
                        effect["duration"],
                        "yes",
                    )

        # Concatenate it
        if prepend_path is not None or append_path is not None:
            sounds = []
            if prepend_path is not None:
                sounds.append(pre_sound)
            sounds.append(synth_main)
            if append_path is not None:
                sounds.append(app_sound)
            synth_main = call(sounds, "Concatenate")

        filepath = filenames[BPF_idx]
        write_wav(filepath, int(synth_main.sampling_frequency), synth_main.values.T)
        call(synth_main, "Save as WAV file", filepath)
