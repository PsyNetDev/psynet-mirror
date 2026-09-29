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

The experiment generates stimuli in real time with Python functions. It samples
pitch intervals densely from a continuous range, so generating each stimulus on
demand is much more efficient than generating every possibility in advance. The
pitch shifting uses the Python package `librosa <https://librosa.org/>`_.
