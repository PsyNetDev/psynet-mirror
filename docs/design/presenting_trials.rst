One page per trial, or several trials on one page?
==================================================

Imagine a mental arithmetic task. The participant sees “7 + 8”, types “15”
and presses Enter. What happens next?

.. grid:: 1 1 2 2
   :gutter: 3

   .. grid-item-card:: One page per trial

      Enter submits the page. PsyNet opens a fresh page with the next sum
      and an empty answer box.

   .. grid-item-card:: Several trials on one page

      The answer box clears and the cursor stays in place. The sum above it
      changes. The participant can start typing again.

Either way, PsyNet saves a separate trial for each sum, including the question
and the participant's answer. This choice applies to one part of your study.
A round of sums can run on one page between ordinary instruction and feedback
pages.

Which experience fits your task?
--------------------------------

**Use ordinary pages** when the built-in prompts and controls fit. This is
also convenient when a trial has several steps. For instance, after each sum
you could ask “How confident are you?” on a separate rating page. A
:doc:`trial maker <trials>` can select the questions. If your timeline
already determines the sequence, you can :ref:`cue trials directly <present-trials-cue>`.

**Keep one page open** when something on screen should persist between
answers. In a speeded arithmetic task, that might be the focused answer box
and a clock counting down the round. You write the JavaScript that updates
the question and handles the response.

How does the next trial reach the page?
---------------------------------------

**If you can choose the sequence up front**, you can send it to the browser
before the first response. Suppose each participant gets twenty shuffled sums.
With the questions already in the browser and local advance enabled, pressing
Enter can display the next sum immediately. If your stimuli include pictures
or sounds, allow time to fetch the media too.

**If the next question depends on the answer**, keep the page open while
PsyNet scores the response and selects the next trial. A correct answer might
earn the participant a harder sum. Even if you wrote every question in advance,
you only discover which one to show after the participant answers. This takes
a server round trip. PsyNet currently supports this on-demand approach for solo
tasks with synchronous scoring.

Implementation examples
-----------------------

:doc:`/code/trials/keeping_a_task_on_one_page` shows both approaches with
working experiments:

- :ref:`Prepare a sequence in advance <single-page-prepared>` for an arrow
  flanker task. :download:`Flanker experiment.py <../../demos/features/live_trial_game/experiment.py>`.
- :ref:`Assign the next trial on demand <single-page-on-demand>` in a
  brightness staircase. :download:`Staircase experiment.py <../../demos/features/live_trial_game_adaptive/experiment.py>`.

For tasks where players react to one another's moves, see :doc:`live_games`.
For groups who each make a choice and then see the results together, see
:doc:`rounds`.
