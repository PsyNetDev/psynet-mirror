.. _concept_participants:

Participants
============

A **participant** is one person taking the experiment, from the moment they
arrive from a recruitment platform until they finish, leave, or are screened
out. PsyNet records each participant's progress through the
:doc:`timeline <timeline>`, their responses, and, if the experiment pays
participants, what they are owed.

Screening
---------

**Pre-screening tasks** at the start of the timeline check that a participant
can do the task, for example that they wear headphones, can tell colors apart,
or understand the instructions. A participant who fails is sent to the end of
the experiment early and, where the recruiter pays for partial completion,
paid for the time spent so far. PsyNet provides
ready-made tasks for common checks, and a pre-screening task is an ordinary
part of the timeline, so you can write your own.

Checks can also run during the main task. A **performance check** at the end
of a trial maker, or after each trial, scores the participant's trials and
can fail the participant and their trials if the score is too low; see
:doc:`trials`.

**Questionnaires** collect information about participants, such as age,
gender, or musical training. PsyNet provides standard questionnaires, and
their answers are stored with the participant.

Payment
-------

If the experiment pays participants, a participant's **reward** has two
parts:

- **time reward**: each part of the timeline has a time estimate, and a
  participant accumulates the estimates of the parts they complete, paid at
  the experiment's hourly wage;
- **performance reward**: an optional extra that you compute from the
  participant's responses, for example a bonus for accurate answers.

The reward is the total a participant should receive. It is paid in two
parts: the recruitment platform's fixed **base payment**, which you set when
you advertise the study, and a **bonus** that PsyNet pays at the end. PsyNet
computes the bonus as the reward minus the base payment, so that the two add
up to the reward. Set the base payment at or below the smallest reward of a
participant who completes the experiment, because a participant whose reward
is lower than the base payment still receives the full base payment and no
bonus.

Paying for estimated rather than measured time means that fast and slow
participants are paid the same for the same work, and that the expected
payment can be advertised in advance. The exception is time spent waiting
for other participants, which is measured up to a limit. Participants who
are screened out or leave early are usually paid for the parts they
completed; what they receive, and how it is split between platform and
bonus, depends on the recruiter.

**Payment limits** protect the budget against mistakes: a maximum payment per
participant, a soft limit on total spending that stops recruitment, and a hard
limit on total spending: a bonus that would exceed it is reduced to the amount
left.

Leaving early and failure
-------------------------

Most participants who leave early are failed by a screening task or
performance check. If you enable the **Leave** button, participants can also
choose to leave; this fails them, and recruiters that pay through PsyNet pay
them only once they have earned a minimum reward. A participant is **failed**
when they should not continue or count as a successful completion, for
example after failing a check. Failing a participant fails their incomplete
trials; completed trials are kept unless a performance check says they are
unusable. A participant who is neither finished nor failed is still in
progress.

Language
--------

Each deployment runs in one **locale**, such as English or German, and every
participant in that deployment sees text in that locale. Text marked for
translation is translated in advance into each language you plan to use, so
the same experiment can run in several languages by deploying it once per
language, each with its own recruitment.

What to check when reviewing participants
-----------------------------------------

- Do the time estimates match how long pages really take? Participants are
  paid by the estimates, so check them against pilot data.
- Are pre-screening tasks placed before the main task, and is their pass
  threshold justified?
- Do the payment limits fit the budget and the expected number of
  participants?
- Is every participant-facing string marked for translation, if the
  experiment will run in more than one language?

.. seealso::

   :doc:`/code/participants/prescreening_and_questionnaires`,
   :doc:`/code/participants/creating_prescreening_tasks`,
   :doc:`/code/participants/payment`,
   :doc:`/code/trials/participant_and_trial_failure` and
   :doc:`/code/participants/internationalization` show these ideas in
   ``experiment.py``.

   Agent Skills for this topic: :doc:`/skills/filter-participants` (pre-
   screening), :doc:`/skills/prepare-for-translation`, :doc:`/skills/prepare-for-cint` and :doc:`/skills/participant-quality-telemetry`.

