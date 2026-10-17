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
high-priority job still waits for one of them to finish, and its
``timeout`` does not count while it waits (see :ref:`async_job_timeout`).
Priority has no effect on a :class:`~psynet.async_job.LocalAsyncJob`, which runs in a thread
of the web process. The CPU table printed after ``psynet test local`` (see
:doc:`/test/scalability`) has one row per job label, priority and place the
job runs in.

.. _async_job_timeout:

Timeouts
--------

A job that runs for longer than its ``timeout`` fails, and so do its trial
and node. The timeout counts from when the job starts running, so time spent
waiting in the queue does not count. Jobs created without a ``timeout`` get
:attr:`~psynet.async_job.AsyncJob.default_timeout`, one hour. Trial,
network and node jobs use the trial maker's ``async_timeout_sec`` (five
minutes by default). An RQ worker stops a
:class:`~psynet.async_job.WorkerAsyncJob` function when it times out; a
:class:`~psynet.async_job.LocalAsyncJob` function keeps running in its
thread, but the job is already marked failed.

.. code-block:: python

    WorkerAsyncJob(refit_model, timeout=4 * 3600).enqueue()

A job that has not started within an hour of being enqueued
(:attr:`~psynet.async_job.AsyncJob.max_queue_wait_sec`) is failed as
probably lost if it can no longer start: a
:class:`~psynet.async_job.WorkerAsyncJob` that RQ no longer has, for
example because its launch failed or Redis restarted, or that RQ failed,
stopped or cancelled, or a :class:`~psynet.async_job.LocalAsyncJob`, which
starts as soon as it is launched. A worker job still waiting in the RQ queue
is a genuine backlog and keeps waiting, however long that takes, and a job a
worker has finished is never failed. Lost jobs are not re-run.

Pending jobs
------------

Low-priority jobs can build up a backlog that is still running after the
last participant has left. PsyNet protects that backlog on docker-ssh
deployments:

* idle hibernation does not put the app to sleep while any job is pending;
* ``psynet export ssh`` and ``psynet export local`` end with a warning that
  jobs are still pending, because the export does not contain their
  results (``psynet export heroku`` does not check); if the jobs cannot be
  checked, the export prints a warning and completes;
* ``psynet destroy ssh`` wakes the app if it is asleep, then refuses to
  destroy it while jobs are pending, or asks you to confirm when run
  interactively.

Wait for the backlog to finish, export again, and then destroy the app. For
example, ``psynet destroy ssh`` prints:

.. code-block:: text

    ❯❯ WARNING: my-study: 12 async jobs are still pending (12 low priority);
    the oldest was enqueued 25 minutes ago. Destroying the app now loses their
    results. Wait for them to finish, then run `psynet export ssh` again
    before destroying the app.

Pass ``--discard-pending-jobs`` to destroy the app anyway, for example when
the jobs can never finish; the command still says how many jobs it discards.
The check queries the app's database from its web container over SSH, so it
works whatever the app's ingress, including a Cloudflare tunnel that is
briefly down. If the app cannot be checked, for example because it runs an
older PsyNet version or its web container is not running, the command prints
a warning that says what to check and destroys the app as before.

A job is pending from :meth:`~psynet.async_job.AsyncJob.enqueue` until it
finishes, fails, times out or is cancelled, and
:class:`~psynet.async_job.LocalAsyncJob` jobs count too, because hibernation
and destroying stop the web process they run in. The experiment's clock
fails timed-out and lost jobs (see :ref:`async_job_timeout`) within about a
minute, so they stop counting as pending; a backlog that is still waiting
in the RQ queue keeps counting however old it is.

API
---

.. Exclude rq.job.Job because sphinx_autodoc_typehints resolves its annotations
.. and can hit an unresolved Redis forward reference even though Job is not
.. rendered on the page.

.. automodule:: psynet.async_job
    :members:
    :show-inheritance:
    :exclude-members: Job
