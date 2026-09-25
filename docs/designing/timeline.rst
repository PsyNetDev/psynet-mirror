.. _concept_timeline:

The timeline
============

The timeline is the path a participant takes through your experiment:
consent, instructions, practice, the main task, questionnaires, and the end
page.

What a timeline is made of
--------------------------

A timeline is a sequence of elements. There are three kinds:

- **Pages** are what the participant sees and responds to: an instruction
  screen, a rating scale, a recording prompt. See
  :doc:`/getting_started/pages`.
- **Page makers** are pages whose content depends on the participant, for
  example "You scored 7 out of 10" or a stimulus chosen from their earlier
  answers.
- **Code blocks** run on the server between pages, where the participant
  can't see them. They assign conditions, compute scores, draw random values,
  or store information for later.

Blocks of repeated trials, such as "rate 40 sounds", are not written out page
by page. They are handled by a *trial maker*, which sits in the timeline as a
single element. See :doc:`trials`.

Remembering things about a participant
--------------------------------------

Each participant has a set of named variables that persist across the
timeline. A page can save its answer into one of these variables, a code
block can set one, and a later page maker can read it back. The experiment
as a whole has its own set of variables for information shared by everyone,
such as a running count.

These variables are how one part of the timeline influences another. When
reading an implementation, it helps to trace each variable: where it is set,
and where it is used.

When code runs
--------------

This is the most common source of subtle mistakes, and it is worth checking
even when an agent wrote the code.

- The overall *shape* of the timeline is built when the server starts, in
  each server process separately. Anything computed at that point is not tied
  to a participant, and a random draw there may differ between server
  processes, so it is not a reliable way to randomize.
- **Code blocks** run once per participant, each time the participant
  reaches them. This is where per-participant randomness belongs.
- **Page makers** run every time the page is displayed, including when the
  participant refreshes. They should only *read* information, never draw new
  random values, or a refresh will change what the participant sees.

The rule of thumb: decide things in code blocks, display them in page makers.

Branching and repetition
------------------------

By default, participants go through the timeline in order. PsyNet provides a
few ways to change that:

- **Conditional**: show one section or another depending on something known
  about the participant, such as their answer to a screening question.
- **Switch**: like a conditional, but choosing between more than two
  sections.
- **While loop**: repeat a section until a condition is met, for example
  practice trials until the participant gets three right.
- **For loop**: repeat a section once for each item in a list worked out for
  that participant, for example one page per instrument they said they play.

Organizing a long timeline
--------------------------

A **module** is a named section of the timeline, such as "practice" or
"questionnaire". Modules make long experiments easier to read and show up in
the dashboard, so you can see where participants are. Sections can also be
defined separately and then combined into the full timeline.

Ending the experiment early
---------------------------

Participants can leave early through an *unsuccessful end*. You rarely write
this yourself. Most early exits happen because PsyNet fails the participant,
for example when they fail a pre-screening task or a trial maker's
performance check. PsyNet then sends them to the unsuccessful end, wherever
they are in the timeline. You can also place an unsuccessful end page
explicitly, for example at the end of a branch for ineligible participants.

If the experiment pays participants, those who leave early are paid what
they have earned so far. See :doc:`/guides/trials/participant_and_trial_failure`
for what happens to their data.

Time estimates
--------------

Every page and trial carries an estimate of how long it should take. PsyNet
adds these up to drive the progress bar and, if the experiment pays
participants by time, to decide how much they are paid. In that case,
payment follows the estimate rather than the clock, so slow participants are
not paid more. Loops need an *expected* number of repetitions so PsyNet can
estimate their length.

Estimates that are much too low make the progress bar misleading and, where
relevant, underpay participants. Compare them against pilot data before
launching.

What to check when reviewing a timeline
---------------------------------------

- Does the order of sections match your design, including practice,
  attention checks, and questionnaires?
- Is every random choice (condition, stimulus order, random values) made in
  a code block or a trial maker, not when the server starts or in a page
  maker?
- For each branch and loop, can you say which participants take which path?
- Which things can end the experiment early (pre-screening tasks,
  performance checks, explicit end pages), and where in the timeline does
  each happen?
- Are the time estimates plausible, including for loops?

.. seealso::

   :doc:`in_code/timeline` shows how each of these ideas appears in
   ``experiment.py``, using the ``demos/features/timeline`` demo.
