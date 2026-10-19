from typing import List, Optional, Union

from .modular_page import BaseAudioPrompt
from .timeline import Event


class Timbre(dict):
    """
    Timbre base class - not to be instantiated directly.
    """


class ADSRTimbre(Timbre):
    """
    ADSR timbre base class - not to be instantiated directly.

    ADSR is an acronym for 'Attack, Decay, Sustain, Release'.
    It is a well-known simple model for the temporal dynamics of an instrument sound.

    Parameters
    ----------

    attack:
        Duration of the 'attack' portion of the sound, in seconds.

    decay:
        Duration of the 'decay' portion of the sound, in seconds.

    sustain_amp:
        Amplitude of the 'sustain' portion of the sound, in seconds,
        where '1' corresponds to the maximum amplitude of the sound
        (as experienced at the transition between the 'attack' and
        'decay' portions).

    release:
        Duration of the 'release' portion of the sound, in seconds.

    """

    def __init__(
        self,
        attack: float = 0.2,
        decay: float = 0.1,
        sustain_amp: float = 0.8,
        release: float = 0.4,
    ):
        super().__init__(
            attack=attack,
            decay=decay,
            sustain_amp=sustain_amp,
            release=release,
        )


class AdditiveTimbre(ADSRTimbre):
    """
    Defines an additive timbre. An additive timbre is defined by a collection
    of frequencies and corresponding amplitudes.

    Parameters
    ----------

    frequencies:
        A list of frequencies, expressed in units of the fundamental frequency.

    amplitudes:
        A list of amplitudes, where 1 is typically the amplitude of the fundamental frequency.

    **kwargs:
        Extra parameters to pass to :class:`~psynet.js_synth.ADSRTimbre`.

    """

    def __init__(
        self,
        frequencies,
        amplitudes,
        **kwargs,
    ):
        super().__init__(**kwargs)
        assert len(frequencies) == len(amplitudes)

        self.frequencies = frequencies
        self.amplitudes = amplitudes
        self.num_harmonics = len(frequencies)

        self["type"] = "additive"
        self["freqs"] = frequencies
        self["amps"] = amplitudes


class HarmonicTimbre(ADSRTimbre):
    """
    Defines a simple harmonic timbre, where all the frequencies are at integer multiples of one another,
    and the amplitudes decline predictably with increasing harmonic number.

    Parameters
    ----------

    num_harmonics:
        Number of harmonics; defaults to 10.

    roll_off:
        Roll-off of the harmonic amplitudes in units of dB/octave; defaults to 12.0.

    **kwargs:
        Extra parameters to pass to :class:`~psynet.js_synth.ADSRTimbre`.
    """

    def __init__(
        self,
        num_harmonics=10,
        roll_off=12.0,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.num_harmonics = num_harmonics
        self.roll_off = roll_off

        self["type"] = "harmonic"
        self["num_harmonics"] = num_harmonics
        self["roll_off"] = roll_off


class CompressedTimbre(ADSRTimbre):
    """
    This is like the :class:`~psynet.js_synth.HarmonicTimbre`, except with the frequencies compressed slightly,
    such that the octave corresponds to a frequency ratio of 1.9 rather than 2.0.

    Parameters
    ----------

    num_harmonics:
        Number of harmonics; defaults to 10.

    roll_off:
        Roll-off of the harmonic amplitudes in units of dB/octave; defaults to 12.0.

    **kwargs:
        Extra parameters to pass to :class:`~psynet.js_synth.ADSRTimbre`.
    """

    def __init__(
        self,
        num_harmonics=10,
        roll_off=12.0,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.num_harmonics = num_harmonics
        self.roll_off = roll_off

        self["type"] = "compressed"
        self["num_harmonics"] = num_harmonics
        self["max_num_harmonics"] = 10
        self["roll_off"] = roll_off


class StretchedTimbre(ADSRTimbre):
    """
    This is like the :class:`~psynet.js_synth.HarmonicTimbre`, except with the frequencies stretched slightly,
    such that the octave corresponds to a frequency ratio of 2.1 rather than 2.0.

    Parameters
    ----------

    num_harmonics:
        Number of harmonics; defaults to 10.

    roll_off:
        Roll-off of the harmonic amplitudes in units of dB/octave; defaults to 12.0.

    **kwargs:
        Extra parameters to pass to :class:`~psynet.js_synth.ADSRTimbre`.
    """

    def __init__(
        self,
        num_harmonics=10,
        roll_off=12.0,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.num_harmonics = num_harmonics
        self.roll_off = roll_off

        self["type"] = "stretched"
        self["num_harmonics"] = num_harmonics
        self["max_num_harmonics"] = num_harmonics
        self["roll_off"] = roll_off


class ShepardTimbre(ADSRTimbre):
    """
    Defines a Shepard tone timbre. Shepard tones are generated by introducing octave transpositions
    for each of the partials provided in a given additive synthesis. Concretely, each of the specified
    partials (e.g. in a harmonic complex tone) is augmented by 2 * num_octave_transpositions octaves,
    positioned symmetrically around each partial frequency. The octave transpositions are weighted using
    Gaussian weights. By default the Gaussian mean is set to 65.5 semitones and has a standard deviation
    of 8.2 semitones.

    Parameters
    ----------

    num_octave_transpositions:
        Number of octave transpositions to use in the Shepard synthesis; defaults to 4.

    shepard_center:
        The mean of the Gaussian weights used in the Shepard synthesis; defaults to 65.5.

    shepard_width:
        The standard deviation of the Gaussian weights used in the Shepard synthesis; defaults to 8.2.

    **kwargs:
        Extra parameters to pass to :class:`~psynet.js_synth.ADSRTimbre`.
    """

    def __init__(
        self,
        num_octave_transpositions=4,
        shepard_center=65.5,
        shepard_width=8.2,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self["num_harmonics"] = 1
        self.num_octave_transpositions = num_octave_transpositions
        self["num_octave_transpositions"] = num_octave_transpositions
        self.shepard_center = shepard_center
        self["shepard_center"] = shepard_center
        self.shepard_width = shepard_width
        self["shepard_width"] = shepard_width


class InstrumentTimbre(Timbre):
    """
    Defines an instrument timbre. The timbre is constructed using the Sampler class of Tone.js with samples
    taken from the MIDI.js Soundfont database (https://github.com/gleitz/midi-js-soundfonts). The Tone.js
    sampler is provided a note-to-sample dictionary which it then uses to synthesize tones for any
    required pitch. This is done by pitch-shifting the nearest pitch sample in the dictionary to the
    desired value, allowing for continuous pitch manipulation.
    For specific implementation details, see (https://github.com/Tonejs/Tone.js/blob/c313bc6/Tone/instrument/Sampler.ts).

    Parameters
    ----------

    type :
        Instrument to select. This can be drawn from a list of built-in options (see below),
        alternatively a custom instrument name can be specified, as long as a dictionary of samples
        is provided to the samples argument.

    samples:
        An optional dictionary of samples to use for synthesis. The keys of this dictionary should be
        note names, for example "F4", "Gb4", and so on. The values should be URLs for the sound files.

    base_url:
        An optional base_url which is prefixed to the URLs in ``samples``.
    """

    def __init__(self, type: str, samples: Optional[dict] = None, base_url=""):
        super().__init__()
        if samples is None:
            assert type in [
                "piano",
                "xylophone",
                "violin",
                "guitar",
                "harpsichord",
                "saxophone",
                "clarinet",
                "flute",
                "trumpet",
            ]
        self["type"] = type
        self["samples"] = samples
        self["base_url"] = base_url
        self["num_octave_transpositions"] = 0


class Chord(dict):
    """
    A chord is a collection of notes to be played to the user.
    Chords can be played using the :class:`~psynet.js_synth.JSSynth` control.

    Parameters
    ----------

    pitches:
        A list of pitches to be played, with each pitch expressed as a number on the MIDI scale,
        where 60 corresponds to middle C (C4) and integer values correspond to semitones.

    duration:
        The duration of the chord, in seconds.
        If left to its default value (`"default"`), then the chord's duration will instead be inherited
        from the ``default_duration`` argument provided to :class:`~psynet.js_synth.JSSynth`.

    silence:
        The length of silence to have after the chord, in seconds.
        If left to its default value (`"default"`), then the chord's duration will instead be inherited
        from the ``default_silence`` argument provided to :class:`~psynet.js_synth.JSSynth`.

    timbre:
        The timbre with which to play the chord, specified as a string.
        There are three different configurations that one can use:

        - Leave both ``timbre`` arguments at their default values of ``"default"``. In this case the chord
          will be played with a standard harmonic complex tone.

        - Set the ``timbre`` argument in :class:`~psynet.js_synth.JSSynth` to a customized timbre,
          for example ``InstrumentTimbre("piano")``, while leaving the timbre argument in :class:`~psynet.js_synth.Chord`
          to its default value. In this case the chord will be played with the customized timbre.

        - Set the ``timbre`` argument in :class:`~psynet.js_synth.JSSynth` to a dictionary of customized timbres,
          and select from this dictionary by specifying an appropriate key in the ``timbre`` argument
          of the :class:`~psynet.js_synth.Chord` object. This provides a way to move between multiple timbres
          in the same sequence.

        Applying the same logic, one may also pass a list of strings, where each element provides the timbre
        for a different note in the chord.

    pan:
        Optional panning parameter, taking values between -1 (full-left) and +1 (full-right).
        If this is provided as a list of numbers then these numbers are applied to the respective
        notes as specified in ``pitches``.

    volume:
        Optional volume parameter, taking values between 0 and 1. Passed directly to JSSynth.
    """

    def __init__(
        self,
        pitches: List[float],
        duration: Union[float, str] = "default",
        silence: Union[float, str] = "default",
        timbre: Union[str, List[str]] = "default",
        pan: Union[float, List[float]] = 0.0,
        volume: float = 1.0,
    ):
        if isinstance(pan, list):
            assert len(pan) == len(pitches)

        if isinstance(timbre, list):
            assert len(timbre) == len(pitches)

        super().__init__(
            pitches=pitches,
            duration=duration,
            silence=silence,
            channel=timbre,
            pan=pan,
            volume=volume,
        )


class Note(Chord):
    """
    A convenience wrapper for :class:`~psynet.js_synth.Chord` where each chord only contains one note.
    This is useful for writing melodies.

    Parameters
    ----------

    pitch:
        The note's pitch, expressed as a number on the MIDI scale,
        where 60 corresponds to middle C (C4) and integer values correspond to semitones.

    **kwargs:
        Further options passed to :class:`~psynet.js_synth.Chord`.
    """

    def __init__(self, pitch: float, **kwargs):
        assert isinstance(pitch, (float, int))
        super().__init__(pitches=[pitch], **kwargs)


class Rest(Chord):
    """
    A convenience wrapper for :class:`~psynet.js_synth.Chord` that defines a rest,
    i.e., a silence of a specified duration.

    Parameters
    ----------

    duration:
        Duration of the rest (in seconds).
    """

    def __init__(self, duration: Union[float, int]):
        assert isinstance(duration, (float, int))
        super().__init__(pitches=[], duration=duration, silence=0.0)


class JSSynth(BaseAudioPrompt):
    """
    JS synthesizer.
    This uses a Javascript library ('js-synthesizer')written by Raja Marjieh,
    which itself depends heavily on the Tone.JS library.
    The API for this synthesizer should be considered experimental and potentially subject to change.

    The synthesizer allows for playing sequences of arbitrary notes or chords.
    Only a limited form of polyphony is supported: specifically, the synthesizer can play chords,
    but all the notes in an individual chord must start and end at the same time.

    Note: due to a limitation of the underlying library, performance will suffer drastically
    if you try and combine Shepard tones with harmonic tones in the same sequence.


    Parameters
    ----------

    text:
        Text to display to the participant. This can either be a string
        for plain text, or an HTML specification from ``markupsafe.Markup``.

    sequence:
        Sequence to play to the participant. This should be a list of objects
        of class :class:`~psynet.js_synth.Chord` or of class :class:`~psynet.js_synth.Note`.

    timbre:
        Optional dictionary of timbres to draw from. The keys of this dictionary should link
        to the timbre arguments of the :class:`~psynet.js_synth.Chord`/:class:`~psynet.js_synth.Note` objects
        in ``sequence``. The values should be objects of class :class:`~psynet.js_synth.Timbre`.
        The default is a harmonic complex tone.

    default_duration:
        Default duration of each chord/note in seconds. This may be overridden by
        specifying the ``duration`` argument in the :class:`~psynet.js_synth.Chord`/:class:`~psynet.js_synth.Note` objects.

    default_silence:
        Default silence after each chord/note in seconds. This may be overridden by
        specifying the ``silence`` argument in the :class:`~psynet.js_synth.Chord`/:class:`~psynet.js_synth.Note` objects.

    text_align:
        CSS alignment of the text (default = ``"left"``).

    controls:
        Whether to give the user playback controls, and which controls (default = ``False``).
        Accepts either a boolean or an iterable (dictionary, set, list).
        False results in no controls being displayed.
        True results in all controls being displayed (Play, Stop, Loop).
        An iterable can be used to select specific controls to display. A list, set, or dictionary with
        empty values will use standard labels. Custom labels can be specified as the dictionary values.
        A boolean, set, or list will result in automatically translated button labels if using translation.
        A dictionary will not be automatically translated - use this to specify custom values for button labels.
    """

    def __init__(
        self,
        text,
        sequence,
        timbre="default",
        default_duration=0.75,
        default_silence=0.0,
        text_align="left",
        controls=False,
    ):
        super().__init__(text=text, text_align=text_align, controls=controls)

        if timbre == "default":
            timbre = HarmonicTimbre()

        if isinstance(timbre, Timbre):
            timbre = dict(default=timbre)

        assert isinstance(timbre, dict)
        for t in timbre.values():
            assert isinstance(t, Timbre)

        uses_panning = False

        assert isinstance(sequence, list)
        for elt in sequence:
            if not isinstance(elt, Chord):
                raise ValueError(
                    "Each element in 'sequence' must be an object of type 'Chord' or 'Note'."
                )
            if isinstance(elt["pan"], list):
                if any([p != 0.0 for p in elt["pan"]]):
                    uses_panning = True
            else:
                _pan = elt["pan"]
                if _pan != 0.0:
                    uses_panning = True
                elt["pan"] = [_pan for _ in elt["pitches"]]

        if uses_panning:
            for t in timbre.values():
                assert isinstance(t, ADSRTimbre), (
                    "Currently panning is only supported for ADSR timbres"
                )

        options = dict(
            max_num_pitches=0,
            max_num_harmonics=1,
            max_num_octave_transpositions=0,
            instruments=[],
        )

        def consolidate_chord(chord):
            x = chord.copy()
            options["max_num_pitches"] = max(
                options["max_num_pitches"], len(x["pitches"])
            )

            if x["duration"] == "default":
                x["duration"] = default_duration
            if x["silence"] == "default":
                x["silence"] = default_silence

            requested_channels = (
                x["channel"] if isinstance(x["channel"], list) else [x["channel"]]
            )
            for requested_channel in requested_channels:
                if requested_channel not in timbre:
                    raise ValueError(
                        f"Selected timbre ({requested_channel}) was not found in timbre list ({timbre})."
                    )

            return x

        chord_sequence = [consolidate_chord(chord) for chord in sequence]

        channels = {key: {"synth": value} for key, value in timbre.items()}

        self.total_duration = 0.0
        for chord in chord_sequence:
            self.total_duration += chord["duration"] + chord["silence"]

        for t in timbre.values():
            if hasattr(t, "num_harmonics"):
                options["max_num_harmonics"] = max(
                    options["max_num_harmonics"], t.num_harmonics
                )
            if hasattr(t, "num_octave_transpositions"):
                options["max_num_octave_transpositions"] = max(
                    options["max_num_octave_transpositions"],
                    t.num_octave_transpositions,
                )
            if isinstance(t, InstrumentTimbre):
                options["instruments"].append(t)

        note_sequence = []
        onset = 0
        for chord in chord_sequence:
            chord["onset"] = onset

            uses_multiple_channels = isinstance(chord["channel"], list)

            if uses_multiple_channels:
                for t in timbre.values():
                    if isinstance(t, ADSRTimbre):
                        raise ValueError(
                            "Mixing multiple timbres within chords is not supported for ADSRTimbres"
                        )

                for i, pitch in enumerate(chord["pitches"]):
                    note = chord.copy()
                    note["pitches"] = [pitch]

                    if isinstance(note["channel"], list):
                        note["channel"] = note["channel"][i]

                    if isinstance(note["pan"], list):
                        note["pan"] = [note["pan"][i]]

                    note_sequence.append(note)

            else:
                assert isinstance(chord["pitches"], list)
                assert not isinstance(chord["channel"], list)

                if not isinstance(chord["pan"], list):
                    chord["pan"] = [chord["pan"]]

                note_sequence.append(chord)

            onset += chord["duration"] + chord["silence"]

        self.stimulus = dict(
            notes=note_sequence,
            channels=channels,
        )
        self.options = options

    macro = "js_synth"

    @property
    def metadata(self):
        return {"stimulus": self.stimulus, "options": self.options}

    def update_events(self, events):
        super().update_events(events)

        events["promptStart"] = Event(is_triggered_by="trialStart")
        events["promptEnd"] = Event(
            is_triggered_by="promptStart", delay=self.total_duration
        )  #
        events["trialFinish"].add_trigger("promptEnd")
