Failure semantics
=================

This page describes how PsyNet implements participant and trial failure. It
is intended for maintainers changing failure, recruiter, sync-group or
timeline code. The rules experiment authors rely on are in
:doc:`/code/trials/participant_and_trial_failure`; keep the two pages
consistent.

Completion, finalization and failure
------------------------------------

A trial has three independent flags:

- ``complete``: a response was submitted.
- ``finalized``: post-trial processing, such as recording analysis, finished
  and the finalization hooks ran.
- ``failed``: the trial is no longer valid. Failure is monotonic; there is no
  way to make a failed trial valid again.

A completed or finalized trial can later be failed, for example by a
performance check. Failing it does not undo participant progress, scores or
payments already awarded.

Participants have the same independence: ``complete`` and ``failed`` are
separate, so a participant who has not reached the end but can still continue
is incomplete, not failed.

Chain growth counts ``finalized`` trials, not ``complete`` ones. A submitted
but unfinalized trial is kept when its participant exits, and can block chain
growth until its asynchronous processing finishes or times out.

``Participant.fail``
--------------------

:meth:`~psynet.participant.Participant.fail` is a no-op for participants who
have already failed. Otherwise, in this order, it:

1. appends the reason to ``failure_tags``;
2. fails every trial with ``complete=False``, including trials created with
   :meth:`~psynet.trial.main.Trial.cue` and other trials not owned by a
   timeline trial maker;
3. runs the registered :class:`~psynet.timeline.ParticipantFailRoutine`
   functions;
4. marks the participant as failed;
5. removes the participant from active sync groups;
6. redirects the participant to ``unsuccessful_end``, unless they are already
   in an end branch or have completed the experiment.

Error recovery passes ``redirect_to_end=False`` because its exit plan handles
the terminal page.

Queued redirects
~~~~~~~~~~~~~~~~

When ``fail()`` is called inside ``advance_page``, for example from a
:class:`~psynet.timeline.CodeBlock`, the redirect is immediate. When it is
called from a background process, such as a response timeout, a recruiter
notification or a dashboard action, the redirect is stored in
``participant.pending_redirect``.

The queued redirect is navigation only; it does not keep the current trial
alive. By the time fail routines run, ``fail()`` has already failed the trial
on screen. The participant's next POST is stored as a ``Response``, and
``advance_page`` then applies the redirect before any other timeline logic,
so ``_finalize_trial`` does not run for that trial. Code must not assume that
an open page means its trial will complete.

Sync groups
~~~~~~~~~~~

Removing a failed participant can drop a
:class:`~psynet.sync.SimpleSyncGroup` below ``min_group_size``. If the group
does not accept top-ups, it is dissolved at once: the remaining members are
removed, and failed when ``fail_participants_below_min_size`` is ``True``. A
barrier applies the same rule if it finds a group below minimum size.

Recruiter exit events
---------------------

Assignment abandonment, marketplace returns (such as a Prolific return) and
reassignment go through ``Experiment._handle_premature_exit``:

- If the participant has completed the experiment, the event is logged and
  ignored. Nothing is written to ``failure_tags``.
- If the participant has already failed, only the recruiter cause tag (for
  example ``assignment_returned``) is appended. PsyNet does not add a second
  ``premature_exit`` tag or rerun trial invalidation. This covers settlement
  returns after an unsuccessful end, such as return-for-bonus.
- Otherwise the cause tag and ``premature_exit`` are appended and
  ``fail()`` runs.

Completion is recorded only when the participant submits the successful end
page. A participant who closes the browser on that page without clicking
*Finish* remains incomplete, so a later abandonment or return fails them and
any unfinished trials, while submitted trials stay.

The trial-maker argument ``fail_trials_on_premature_exit`` is deprecated and
ignored; passing ``True`` emits a ``DeprecationWarning``.

Node ownership
--------------

:attr:`~psynet.participant.Participant.failure_cascade` returns an empty
list, so failing a participant never fails the nodes or networks they own.
Recruiter return, abandonment and reassignment previously called Dallinger's
``fail_participant``, which failed every node the participant owned. In a
within-participant chain the start node belongs to the participant, and
failing a degree-0 start node fails the whole network. PsyNet now leaves
chain nodes and networks unfailed. ``failed`` means that an object's content
should not be used, not that a private chain has been retired.

Dallinger hooks
---------------

:meth:`~psynet.experiment.Experiment.fail_participant` is a compatibility
shim that calls :meth:`~psynet.participant.Participant.fail`. Defining an
``Experiment`` subclass that overrides it raises a ``RuntimeError``.

Dallinger's ``data_check`` and ``attention_check`` run after submission and
would set the participant status to ``bad_data`` or ``did_not_attend``.
PsyNet's ``data_check_failed`` and ``attention_check_failed`` only log a
warning, and the experiment configuration check raises a ``RuntimeError`` if
an experiment overrides any of these four hooks. Quality screening happens
during the timeline through
:meth:`~psynet.trial.main.TrialMaker.performance_check` or
:meth:`~psynet.participant.Participant.fail`.
