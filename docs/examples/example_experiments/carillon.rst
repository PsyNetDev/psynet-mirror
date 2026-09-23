.. _consonance_carillon:

Consonance and the carillon
===========================

Source: https://github.com/pmcharrison/2022-consonance-carillon

This experiment is part of a series of studies on the interaction between timbre and consonance.
This particular experiment studies the *carillon*, a kind of pitched bell often found in churches.
In the experiment participants are played different pairs of tones synthesized using
a carillon timbre, and are asked to rate them for 'pleasantness' on a numeric scale.
The tones are synthesized by taking a library of audio samples recorded from a real carillon
and pitch-shifting them to reach a desired pitch.

This experiment illustrates a particularly important feature of PsyNet: the real-time
generation of stimuli using Python functions. This experiment involves sampling stimuli
densely from a continuous range of pitch intervals, so it is much more efficient to generate
stimuli on-demand than to try and generate all possibilities in advance. The code to
generate the stimuli takes advantage of the powerful Python package
`librosa <https://librosa.org/>`_,
which contains a sophisticated pitch shift algorithm that is used to generate the
stimuli.
