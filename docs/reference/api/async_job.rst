==========
Async jobs
==========

.. _async_job_priority:

Job priority
------------

Each :class:`~psynet.async_job.WorkerAsyncJob` runs at ``"high"`` or ``"low"``
priority. Workers take jobs from the high-priority queue first, so a
participant who is waiting for an analysis does not queue behind analyses
that nobody is waiting for. Unless you choose a priority, PsyNet picks one:

* :class:`~psynet.timeline.AsyncCodeBlock`: high with ``wait=True``, low with
  ``wait=False``.
* :meth:`~psynet.trial.main.Trial.async_post_trial`: high if

  * the trial maker checks performance (``check_performance_at_end`` or
    ``check_performance_every_trial``);
  * the trial maker is a within-participant chain trial maker
    (``chain_type="within"``), because the participant's next trial in a
    chain waits for the previous trial to be finalized; or
  * the trial class overrides :meth:`~psynet.trial.main.Trial.show_feedback`
    or :meth:`~psynet.trial.main.Trial.gives_feedback` and keeps
    ``wait_for_feedback = True``.

  Low otherwise. Across-participant chains are low because participants are
  usually given another chain while one grows; if your participants often
  wait for chains (for example with ``wait_for_networks=True`` and few
  chains), set ``async_post_trial_priority = "high"``.
* :meth:`~psynet.trial.main.TrialNetwork.async_post_grow_network` and
  :meth:`~psynet.trial.main.TrialNode.async_on_deploy`: high, because
  participants may wait for the next node.
* A :class:`~psynet.async_job.WorkerAsyncJob` you create yourself: high.

To override the choice:

.. code-block:: python

    AsyncCodeBlock(save_summary, wait=False, priority="high")

    class MyTrial(StaticTrial):
        async_post_trial_priority = "low"

    WorkerAsyncJob(refit_model, priority="low").enqueue()

Priority only decides which waiting job starts next; a running job is never
interrupted. If every worker is busy with long low-priority jobs, a
high-priority job still waits for one of them to finish. Priority has no
effect on a :class:`~psynet.async_job.LocalAsyncJob`, which runs in a thread
of the web process. The CPU table printed after ``psynet test local`` (see
:doc:`/test/scalability`) has one row per job label, priority and place the
job runs in.

Low-priority jobs can build up a backlog that is still running after the
last participant has left. PsyNet protects that backlog on docker-ssh
deployments:

* idle hibernation does not put the app to sleep while any job is pending;
* ``psynet export`` warns that jobs are still pending, because the export
  will not contain their results;
* ``psynet destroy ssh`` refuses to destroy an app with pending jobs, or asks
  you to confirm when run interactively.

Wait for the backlog to finish, export again, and then destroy the app. For
example, ``psynet destroy ssh`` prints:

.. code-block:: text

    ❯❯ WARNING: my-study: 12 async jobs are still pending (12 low priority);
    the oldest was enqueued 25 minutes ago. Destroying the app now loses their
    results. Wait for them to finish, then run `psynet export ssh` again
    before destroying the app.

Pass ``--discard-pending-jobs`` to destroy the app anyway, for example when
the jobs can never finish. A job is pending from
:meth:`~psynet.async_job.AsyncJob.enqueue` until it finishes, fails, times
out or is cancelled, and :class:`~psynet.async_job.LocalAsyncJob` jobs count
too, because hibernation and destroying stop the web process they run in.

API
---

.. Exclude rq.job.Job because sphinx_autodoc_typehints resolves its annotations
.. and can hit an unresolved Redis forward reference even though Job is not
.. rendered on the page.

.. automodule:: psynet.async_job
    :members:
    :show-inheritance:
    :exclude-members: Job
