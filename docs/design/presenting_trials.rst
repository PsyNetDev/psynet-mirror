Presenting a sequence of trials
===============================

Imagine a brightness staircase. The participant presses an arrow key to choose
the brighter of two patches. PsyNet scores the answer and the staircase uses
it to choose the brightness difference for the next pair.

You could give each pair its own trial page, followed by a feedback page.
Or you could keep two squares on screen and change their brightness after each
keypress. Both designs can use the same :doc:`staircase trial maker <chains>`.
Both save one trial per comparison, with the assigned stimulus, answer and score.

What should happen after a response?
------------------------------------

**Use ordinary trial pages** when the timeline should move on to another
screen or control. For example, show a pair, collect the answer, then play a
sound or give feedback before continuing. This is the simplest place to start.
A :doc:`trial maker <trials>` can choose the stimuli, balance assignments, or
run a staircase. If the timeline can choose each trial itself, you can
:ref:`cue a trial directly <present-trials-cue>`.

**Keep one page open** when the participant should keep looking at the same
interface. A stream of words can appear in the same spot, or two patches can
change in place. The trial maker still selects and records each trial. You
provide the JavaScript that draws each new stimulus on the page. Which
presentation option to use depends on when the next assignment is known.

When can you choose the next stimulus?
--------------------------------------

**Before the first response.** In an arrow flanker task, the researcher can
shuffle the arrows separately for each participant as soon as they start.
A ``LiveTrialGame`` can prepare those trials up front. If the page has the
upcoming stimuli and is configured to advance locally, it can show the next
one immediately after a keypress. For pictures or sounds, allow time to fetch
the media too. See :ref:`how to prepare a sequence <present-trials-prepared>`
or download the :download:`flanker experiment.py <../../demos/features/live_trial_game/experiment.py>`.

**After the current response.** In the brightness task, a correct response at
a gap of 24 leads to a gap of 16. An error leads to 32. With an
``OnDemandTrialGame``, PsyNet completes the trial, asks the maker for the
next assignment and returns it to the same page. Each transition takes a
server round trip. This option supports solo tasks with synchronous scoring.
See :ref:`how to present trials on demand <present-trials-on-demand>` or
download the :download:`staircase experiment.py <../../demos/features/live_trial_game_adaptive/experiment.py>`.

Think about the **participant's sequence**. You might have all 500 paintings
on disk before recruitment and still need on-demand selection because each
rating determines which painting to show next.

What does the page receive?
---------------------------

By default the live page receives the saved ``trial.definition``. In the
brightness task this includes the gap and both grey values, so reloading
shows the same pair. Override ``get_public_definition(trial)`` when the browser
needs a different representation. VocabTest sends a word image URL and keeps
the scoring key on the server.

Does one player need to react to another?
-----------------------------------------

If two people need to see and respond to each other's moves as they happen,
such as offers in a negotiation, read :doc:`live_games`. If everyone makes
a choice and then sees the group's results together, read :doc:`rounds`.
