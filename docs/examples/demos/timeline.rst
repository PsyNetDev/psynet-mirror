Timeline
========

This demo shows the timeline control-logic constructs, such as
Conditionals, Switches, and While Loops. These determine which pages the
participant sees depending on what they have done in the experiment so far.
Run it from ``demos/experiments/timeline``; :doc:`/getting_started/timelines`
explains the same constructs step by step.

Source: ``demos/experiments/timeline``

As part of the control logic we see the use of the argument ``fix_time_credit``.
Ordinarily PsyNet participants receive credit for each page that they complete,
and this credit can be used to determine their payment. This can be dangerous in the
case of While Loops, though, because a participant could theoretically receive
infinite credit by going around the same While Loop many times. We can prevent this
behavior by setting ``fix_time_credit=True`` in the corresponding While Loop.

This demo also illustrates the **Page Maker**.
A Page Maker creates pages on-the-fly, giving it the ability to respond to the
current state of the participant and indeed of the larger experiment.

We see also the use of several **Modular Pages**.
Modular Pages are a pattern for defining pages where we combine a
Prompt (e.g. text, audio, video), typically representing some kind of stimulus,
and a Control (e.g. rating, slider), whereby the participant responds.


.. literalinclude:: ../../../demos/experiments/timeline/experiment.py
   :language: python
