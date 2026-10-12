Local deployments
=================

Use a local deployment when collecting data on a computer in a laboratory or
in the field. Unlike disposable local debugging, every local deployment has a
required ID:

.. code-block:: bash

    psynet deploy local --id gibbs

The ID contains lowercase letters, digits, and dashes. It is scoped to the
experiment directory and identifies a history of database snapshots under
``data/snapshots/<id>/``.

Managed local snapshots currently support the standard and ``--legacy`` local
runners, but not ``--docker``.

Only one local experiment can use the shared PostgreSQL database at a time.
Starting a second ``psynet deploy local`` while another is still running
asks you to stop the running experiment first. Sequential launches after a
normal stop do not hit this error; they offer the previous snapshot history
instead.

Snapshots
---------

PsyNet creates a database snapshot when a participant finishes, every ten
minutes when the database has changed since the last snapshot, after a
normal shutdown (when needed), and before resetting the local database to
start another experiment. Snapshots are private, non-anonymized recovery
files for resuming on the same machine. They do not include assets or
replace a full :ref:`data export <data>`.

Before that recovery snapshot, ``psynet deploy local`` stops leftover
PsyNet worker processes and any ``flask run`` development server using this
database. If one of them is still running, the command refuses to reset the
database, so a writer cannot commit into a database the archive does not
contain. A server whose environment cannot be read, including one started by
another account on this machine, is treated the same way. Stopping the
running deployment with Ctrl-C or SIGTERM writes the shutdown snapshot before
the process exits. A second Ctrl-C during that copy does not leave a numbered
archive without its metadata.

The ten-minute timer skips a backup when the ``response`` table is empty
and there is no prior snapshot, or when the response watermark has not
grown and a fingerprint of every public table still matches the last
archive. That fingerprint changes when any row is inserted, updated, or
deleted, not only when a new response id appears. If the watermark or the
fingerprint cannot be read, the timer still writes a snapshot. Long-running
experiments therefore do not accumulate identical backups during quiet
periods.

Finish-time snapshots are on by default for managed local live deployments.
Disable them in ``config.txt`` or ``Experiment.config`` if they are too costly
on the machine you are using::

    snapshot_on_participant_finish = false

If the last snapshot was taken because a participant finished, and no later
participant started, PsyNet skips the shutdown snapshot when that archive's
database fingerprint still matches the live database. Shutdown still
snapshots when a participant is in progress, when finish-time snapshots are
disabled, when nobody has finished yet, or when any table has changed since
the last archive.

An archive without its metadata, metadata without its archive, or metadata
that cannot be read is not offered as a resume point. ``psynet deploy local``
stops and tells you to repair or remove that pair, rather than starting from
an older snapshot and leaving the newer one behind. A newer broken pair also
forces a recovery snapshot before the database is reset.

Running the same command again displays the ten most recent snapshots and asks
which one to resume. The latest is selected by default. Scripts can bypass the
prompt:

.. code-block:: bash

    psynet deploy local --id gibbs --snapshot latest
    psynet deploy local --id gibbs --snapshot 4

Before resetting the shared local PostgreSQL database, PsyNet checks whether it
contains an interrupted managed deployment. If so, PsyNet saves a recovery
snapshot in the owning experiment directory. A failed recovery prevents the
new deployment from starting.

A database left behind by ``psynet debug local`` is discarded without
prompting, because debugging runs are disposable. The same applies to a
database that was only prepared and never launched. Any other mode, including
``bot``, is kept.

A local database from a live or sandbox run that PsyNet cannot account for,
such as one created before this snapshot system, is never discarded silently.
Adopt it explicitly after checking that the current experiment directory
contains the matching source:

.. code-block:: bash

    psynet deploy local --id gibbs --adopt-existing

Deployment history
------------------

Local deploy and snapshot events are recorded in
``data/deployment-events.jsonl``. The same file also covers remote deploy,
sandbox, export, destroy, and operator comments. See
:doc:`history` for ``--comment``, ``psynet comment``, and
``psynet history``.
