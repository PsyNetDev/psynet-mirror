Emotions of musical scales
==========================

Source: https://github.com/pmcharrison/2022-musical-scales

This experiment studies the emotional connotations of different musical scales.
The paradigm involves taking a base set of melodies and playing them in a variety of
different musical scales, and asking the participant to rate their expressed emotions
on numeric scales.

The stimuli are generated in Python from the factorial combination of base
melodies and musical scales. They are played with JSSynth, a browser-based
synthesizer included in PsyNet that plays long stimuli such as melodies without
any audio download time.

The rating interface, which lets participants rate several emotions at once, is
built with `SurveyJS <https://surveyjs.io/>`_, as are the demographic
questionnaires at the end of the experiment.
