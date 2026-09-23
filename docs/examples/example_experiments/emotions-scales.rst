Emotions of musical scales
==========================

Source: https://github.com/pmcharrison/2022-musical-scales

This experiment studies the emotional connotations of different musical scales.
The paradigm involves taking a base set of melodies and playing them in a variety of
different musical scales, and asking the participant to rate their expressed emotions
on numeric scales.

One important PsyNet feature that this experiment illustrates is the programmatic generation of
stimuli. There's a large number of stimuli that stem from the factorial combination
of different base melodies with different musical scales, and it is very natural to explore
these different combinations directly in Python. These stimuli can then be rendered
using JSSynth, a simple browser-based synthesizer included in PsyNet that is good for playing
long stimuli such as melodies without requiring any audio download time.

Another important feature this experiment illustrates is the integration with the
popular `SurveyJS <https://surveyjs.io/>`_ survey creator tool.
This tool is used here to implement a clean and intuitive user interface that allows the user to
rate multiple emotions at the same time. It's also used for the demographic questionnaires
presented at the end of the experiment.
