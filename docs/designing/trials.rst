.. _concept_trials:

Static trial makers
===================

Most experiments have a main task where participants respond to a series of
stimuli: rating sounds, choosing between images, singing back melodies.
PsyNet runs such tasks with **trial makers**, **nodes**, and **trials**.

This page describes *static* experiments, where the nodes are fixed before
the experiment starts. :doc:`Chain experiments <chains>` follow the same
pattern, except that new nodes are made from participants' responses.

How it works
------------

A **trial maker** runs the task. It holds a set of **nodes**, each carrying a
small record of information called its *definition*, such as
"sound: clarinet". Stimulus files live in the experiment's ``static/``
folder, and the definition records which file to use (see :doc:`stimuli`).

Participants visit nodes one at a time. At each visit:

1. The trial maker picks a node for the participant.
2. PsyNet creates a **trial**, the record of this participant's visit to
   this node. The trial starts with a copy of the node's definition and can
   add random variation of its own.
3. The participant sees a page built from the trial's definition, and
   responds.
4. The answer is stored on the trial.

The participant then moves on to another node, until the trial maker
decides they have done enough, and they continue with the rest of the
:doc:`timeline`.

What a node holds is up to you. Usually it is one stimulus, but it can
equally be a question, a topic, or a condition. Trials on the same node
share its definition, so PsyNet treats them as responses to the same thing
when it balances and counts responses.

What the trial adds
-------------------

Often the node's definition is all a trial needs. When a trial adds
something of its own, it is usually random variation, so that visits to the
same node are not identical. For example:

- playing the node's sound at a random volume;
- roving the pitch of a chord;
- shuffling the order of the response options;
- randomizing which side the correct answer appears on;
- drawing a random color to rate, when the node is a question such as
  "how angry is this color?".

The variation is drawn once, when the trial is created, and stored with the
trial. Refreshing the page does not change it, and the exported data records
exactly what each participant was shown.

Choosing the next node
----------------------

The trial maker controls which nodes each participant visits:

- **How many visits.** An expected number per participant, used for time
  estimates, and optionally a maximum. Often this is "one per node".
- **Balancing.** By default, the trial maker favors the node with the fewest
  responses so far across all participants, so responses accumulate evenly.
- **Repeats.** Whether a participant may visit the same node more than once.
  Separately, a few **repeat trials** can be added at the end, revisiting
  earlier nodes to estimate how consistent each participant is.
- **Blocks.** Nodes can be grouped into blocks, such as "strings" and
  "brass". Participants finish one block before starting the next. The block
  order is random for each participant unless you choose otherwise. With one
  node per block, this is also how you fix a stimulus order for everyone.
- **Participant groups.** Nodes can be reserved for groups of participants,
  such as "musicians" and "non-musicians", or two between-participant
  conditions. You decide how participants are assigned to groups, for
  example at random or from a questionnaire answer; PsyNet requires this
  rule whenever nodes are reserved for groups.

A trial maker can also decide when recruitment stops: once enough
participants have finished it, or once every node has enough responses.

After the response
------------------

Once the answer is stored, the trial can:

- **score the answer**, for example correct or incorrect;
- **give feedback**, such as "Correct!" or a comparison with other
  participants;
- **analyze a recording** on the server, for example to check that the
  participant actually sang. Analysis runs in the background. By default,
  feedback waits for it to finish, so feedback can use the result.

A trial maker can also run a **performance check**, either after every trial
or once at the end. PsyNet provides three kinds of check, each compared with
a threshold you choose:

- **Score**: the participant's total score across trials.
- **Performance**: the proportion of their trials that did not fail.
- **Consistency**: how well their answers on repeat trials agree with their
  first answers.

You can also write your own rule. Participants who fail the check leave the
experiment through the unsuccessful end (see :doc:`timeline`). This is how
most screening and attention tasks are built.

By default, when a participant fails a performance check, their trials in
that trial maker are marked as **failed** too. A failed trial is not deleted:
it stays in the database and the export, marked as failed, but PsyNet leaves
it out of balancing and recruitment targets, and analyses normally leave it
out too. Participants who simply leave early keep the trials they completed. See
:doc:`/guides/trials/participant_and_trial_failure` for the full rules.

Where relevant, scores can also feed a performance bonus.

Where the data goes
-------------------

Each trial becomes one row in the exported data, with its definition
(including any random variation), the participant, the answer, the score,
and whether the trial failed. Nodes are exported too. When planning the analysis, check that
everything you need is either in the definition or in the answer.

What to check when reviewing trials
-----------------------------------

- Does each node's definition contain everything the analysis needs, such as
  stimulus identity and condition?
- Is each trial's random variation stored in its definition, so it appears
  in the data?
- Does the trial page show what you intended, and does it prevent the
  participant from responding too early, for example before the sound has
  finished?
- How many trials does each participant do, and will balancing give each node
  roughly the number of responses you need?
- If there are blocks or participant groups, is the order and assignment what
  the design specifies?
- If there is a performance check, what is the threshold, and what happens to
  participants who fail it?

.. seealso::

   :doc:`in_code/trials` shows how each of these ideas appears in
   ``experiment.py``, using the ``demos/pipelines/simple_rating`` demo.
