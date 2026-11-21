Trials and pages
================

A :doc:`trial <trials>` records one participant's encounter with a stimulus.
A :doc:`page <pages>` is a step on the participant's timeline. How the two
fit together depends on what you want to measure and what the participant
should do next.

One page per trial
------------------

In a music-rating study, a participant listens to a song excerpt and rates
how much they like it. That rating completes their response to the excerpt.
The next page plays another song.

This is a good starting point when a prompt and a response control cover the
whole trial. You can combine an audio prompt with a rating scale using
PsyNet's built-in controls. Submitting the page advances the timeline.
PsyNet normally swaps the content in place, so moving to the next song
doesn't require a browser reload.

Several pages per trial
-----------------------

In a recognition study, a participant sees a face and decides whether they
have seen it before. Once they commit to an answer, the face disappears and
a second page asks how confident they are. The decision and the confidence
rating are two observations about the same face.

Use this arrangement when a trial has distinct stages that should appear
in order. Here, putting confidence on its own page lets you ask about a
decision the participant has already made. Return the pages together from
``show_trial()``. To store both responses in the trial's answer, give the
pages distinct labels and set ``accumulate_answers = True`` on the trial.

Several trials on one page
--------------------------

In an art-sorting task, a participant swipes paintings left or right. As one
painting follows their finger off screen, the next slides into view beneath
it. Each painting gets its own trial and answer, while one page handles the
gestures and animation for the whole deck.

Use a live page when the interaction itself spans trials. Your JavaScript
handles each swipe and sends the answer to PsyNet. The timeline advances
when the round ends. If you simply want the interface to stay on screen
while the timeline advances after each answer, consecutive ordinary pages
can also share a ``session_id``. See :doc:`how page transitions work
</developer/page_lifecycle>`.

On a live page, consider when you can select the next stimulus:

- **A prepared sequence.** If you shuffle the deck before the round, you can
  send the sequence to the browser and preload the pictures. With local
  advance enabled, the next painting can appear as soon as the participant
  swipes. The :ref:`prepared sequence recipe <single-page-prepared>` shows
  this pattern with a :download:`flanker task <../../demos/features/live_trial_game/experiment.py>`.
- **An on-demand sequence.** If each response determines what to show next,
  the page waits for PsyNet to score the answer and return the next trial.
  This takes a server round trip and currently supports solo tasks with
  synchronous scoring. The :ref:`on-demand recipe <single-page-on-demand>`
  uses an :download:`adaptive brightness task <../../demos/features/live_trial_game_adaptive/experiment.py>`.
