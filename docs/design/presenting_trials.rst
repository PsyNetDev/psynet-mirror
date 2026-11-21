Trials and pages
================

Imagine a mental arithmetic task. The participant sees “7 + 8”, types “15”
and presses Enter. What happens next?

.. grid:: 1 1 3 3
   :gutter: 3

   .. grid-item-card:: One page per trial

      Enter submits the answer. The next timeline page shows a new sum
      and an empty answer box.

   .. grid-item-card:: Several pages per trial

      Enter submits the answer. A second page asks “How confident are you?”
      Both responses belong to the same sum. The next trial starts after
      the confidence rating.

   .. grid-item-card:: Several trials on one page

      Enter sends the answer to the live game. The same timeline page
      clears the box and displays the next sum. The cursor stays in place.

In all three designs, each sum is one trial. You can use ordinary instruction
and feedback pages on either side of the round.

Which experience fits your task?
--------------------------------

**Use ordinary pages** when the timeline should advance after each response.
PsyNet normally replaces the page content in place, so participants can move
to the next question without a browser reload. Consecutive pages can even
share a ``session_id`` to keep the same interface on screen. Each submission
still advances to the next timeline page. See
:doc:`how page transitions work </developer/page_lifecycle>`.

For a multi-page trial, return the pages together from ``show_trial()``.
Set ``accumulate_answers = True`` on the trial to keep both the arithmetic
answer and the confidence rating under their page labels.
A :doc:`trial maker <trials>` can select the questions. If your timeline
already determines the sequence, you can :ref:`cue trials directly <present-trials-cue>`.

**Use one live page for the round** when the task should advance through
trials within that page. For a speeded arithmetic round, your JavaScript can
handle Enter, clear the box and display the next sum while the round clock
keeps ticking. The timeline moves on when the round finishes.

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
