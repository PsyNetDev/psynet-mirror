Pitch-matching test
===================

Source: https://github.com/pmcharrison/2022-vertical-processing-test

This experiment studies the ability of participants to sing back particular notes
within musical chords. This is an important ability for musicians, especially those
who sing in choirs or who conduct music ensembles. It's also an interesting task
psychologically speaking, because it probes fundamental pitch processing mechanisms
as well as cognitive prototypes for different musical chords.

One important PsyNet feature showcased in this implementation is the ability to record
audio from the participant and process it during the experiment. In particular,
we run a pitch detection algorithm on the participant's recording to identify which
notes they sang; these results can then be used to deliver feedback to the participant,
and could in theory be used to screen out poorly performing participants.

The experiment also includes a simple music notation viewer, which is used to give
feedback to the participants. Here it simply shows the original chord that the participant heard
alongside the notes that the participant actually sung.
