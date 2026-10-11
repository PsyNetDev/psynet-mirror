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
high-priority job still waits for one of them to finish. A job's
``timeout`` counts from when it starts running, so queue wait does not count
towards it. A job that has not started within an hour of being enqueued is
failed as probably lost if RQ no longer holds it, for example because its
launch failed or Redis restarted; a job still waiting in the RQ queue is a
genuine backlog and keeps waiting (see
:attr:`~psynet.async_job.WorkerAsyncJob.max_queue_wait_sec`). Priority has no
effect on a :class:`~psynet.async_job.LocalAsyncJob`, which runs in a thread
of the web process. The CPU table printed after ``psynet test local`` (see
:doc:`/test/scalability`) has one row per job label, priority and place the
job runs in.

API
---

.. Exclude rq.job.Job because sphinx_autodoc_typehints resolves its annotations
.. and can hit an unresolved Redis forward reference even though Job is not
.. rendered on the page.

.. automodule:: psynet.async_job
    :members:
    :show-inheritance:
    :exclude-members: Job
