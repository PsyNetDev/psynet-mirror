Handling failed participants and trials
=======================================

A failed **participant** leaves the experiment early through the unsuccessful
end and does not count as a successful completion. A failed **trial** stays in
the database and the export, marked as failed, but PsyNet leaves it out of
balancing, recruitment targets and chain growth. The two are independent: a
participant can be failed while their completed trials stay valid, and a
trial can fail without failing its participant.

Failing a trial
---------------

Call :meth:`~psynet.trial.main.Trial.fail` with a reason. The reason is stored
in the trial's ``failed_reason`` field. Failure cannot be undone. In
``demos/experiments/create_and_rate/gap``, creators can reject their own
recording:

.. literalinclude:: ../../../demos/experiments/create_and_rate/gap/experiment.py
   :pyobject: CreateTrial.format_answer

PsyNet also fails trials itself:

- when recording analysis returns ``"failed": True``;
- when the participant has not responded ``response_timeout_sec`` seconds
  after the trial was created (a trial maker attribute, default five
  minutes). If they submit later, the answer is still stored, but the trial
  stays failed and the participant is not failed;
- when the participant fails or leaves before completing the trial.

Failing a participant
---------------------

Call :meth:`~psynet.participant.Participant.fail` with a reason, which is
appended to ``participant.failure_tags``. PsyNet then:

- fails the participant's incomplete trials, including the one on screen,
  and keeps their completed trials;
- removes them from any sync groups;
- sends them to the unsuccessful end, unless they have already finished.

When ``fail()`` runs in the timeline, for example in a
:class:`~psynet.timeline.CodeBlock`, the redirect is immediate. When it runs
in a background process, such as a timeout or an action on the dashboard,
the participant is redirected the next time they submit a page.

A participant who has already finished can still be failed, for example after
checking their data; they are not redirected. To run extra code whenever a
participant is failed, place a :class:`~psynet.timeline.ParticipantFailRoutine`
in the timeline. Do not override
:meth:`~psynet.experiment.Experiment.fail_participant`; PsyNet raises an
error if an experiment does.

Participants who leave early
----------------------------

When the recruiter reports that a participant has abandoned or returned the
study, or been reassigned, PsyNet fails the participant with the tag
``premature_exit``. As with any participant failure, their incomplete trials
fail and their completed trials stay. Participants who have already
completed the experiment are not affected.

To control how many participants or responses are collected, use
``recruit_mode="n_participants"`` or ``recruit_mode="n_trials"`` on the trial
maker, not trial failure.

Performance checks
------------------

When a participant fails a trial maker's performance check,
``fail_trials_on_participant_performance_check`` decides whether their
completed trials in that trial maker fail too. Set it to ``True`` when failing
the check means the responses should not be analyzed, as with bots, nonsense
responses or failed attention checks. Set it to ``False`` when the check only
decides whether the participant may continue, so the collected trials remain
valid measurements. The setting applies to each trial maker separately.

The defaults are:

.. list-table::
   :header-rows: 1

   * - Trial maker
     - Completed trials after a failed performance check
   * - :class:`~psynet.trial.static.StaticTrialMaker`
     - Failed
   * - Dense trial makers (:mod:`psynet.trial.dense`)
     - Failed
   * - :class:`~psynet.trial.chain.ChainTrialMaker`
     - Kept
   * - :class:`~psynet.trial.graph.GraphChainTrialMaker`
     - Kept
   * - Built-in pre-screening tasks
     - Failed, except ``FreeTappingRecordTest``, which keeps them

Chain trial makers keep completed trials by default because failing a trial
can also fail the nodes built from it, as described in the next section.

Failure propagation
-------------------

``propagate_failure`` (default ``True`` for chain trial makers) decides
whether failing a trial also fails the objects built from it. When a
finalized trial contributed to the next node in a chain, failing the trial
fails that node (``node.child``) and its descendants. An incomplete trial
never contributed to a node, so failing it does not propagate. Enable
propagation only where the later objects' validity depends on the failed
trial.

Within-participant chains stay unfailed when their participant fails. Their
completed trials follow the performance-check setting above.

Failed trials in analysis
-------------------------

Exported trial tables include ``failed`` and ``failed_reason`` columns, and
the participant table includes ``failure_tags``. Analyses normally leave out
failed trials. In code, ``participant.alive_trials`` and
``node.alive_trials`` list the trials that have not failed, and queries can
filter on the column:

.. code-block:: python

    StaticTrial.query.filter_by(trial_maker_id="ratings", failed=False).all()

.. seealso::

   :doc:`/reference/api/participant` and :doc:`/reference/api/trial/main` in
   the API reference.
