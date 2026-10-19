.. _performance_testing:

===================
Testing scalability
===================

``psynet performance-test`` keeps a target number of bots active on a running
experiment and reports response times, throughput and queue delays. Use it
to choose how many participants to run at once, and how many worker
processes they need.

Run it once :doc:`back-end tests <backend>` pass.

Measuring async job CPU
-----------------------

At the end of ``psynet test local``, PsyNet logs how much CPU each kind of
async job used, grouped by where the job runs, label and
:ref:`priority <async_job_priority>`:

.. code-block:: text

    Async job CPU time (CPU-heavy: mean CPU >= 50% of mean wall time):
      Runs in  Label           Priority  Count  Mean CPU (s)  Max CPU (s)  Mean wall (s)  CPU-heavy
      worker   AsyncCodeBlock  high          2         0.027        0.052          0.085         no

``worker`` rows are :class:`~psynet.async_job.WorkerAsyncJob` jobs, which run
in worker processes. ``web`` rows are :class:`~psynet.async_job.LocalAsyncJob`
jobs, such as asset deposits, which run in a thread of the web process. A
CPU-heavy worker job keeps a core busy while it runs, so as load grows it
needs more worker processes and a server with a core for each (see
:ref:`performance_testing_async_workers`). An I/O-bound job, such as an API
call, mostly waits and doesn't need more cores. Per-job values are in the
``cpu_time`` column of ``database/async_job.csv`` in the export. The
:doc:`/skills/plan-server-resources` Agent Skill turns these numbers into a
worker estimate; confirm it with a performance test.

Running a test
--------------

From the experiment directory:

.. code-block:: bash

    psynet performance-test local

This starts a local server with its own port, database and Redis, keeps
``Experiment.test_n_bots`` bots active for about one and a half participant
sessions, prints a report and shuts the server down. To compare several
levels of load, pass a comma-separated list; PsyNet runs one test per value
and prints a summary comparing them:

.. code-block:: bash

    psynet performance-test local --n-bots "5,10,20,40"

Add ``--existing`` to test a server that is already running, for example
from ``psynet debug local``. Local experiments share one PostgreSQL server,
which allows 100 connections by default, so a few hundred bots or several
runs at once can exhaust it ("sorry, too many clients already"); see
:doc:`/developer/running_tests`.

Local results only describe your computer. To choose participant numbers,
test the deployment server (see :ref:`performance_testing_server`).

The main options are:

``--n-bots``
    The number of bots to keep active, a comma-separated list, or ``auto``
    to find the server's capacity (see :ref:`performance_testing_capacity`).
    Finished bots are replaced.

``--duration-minutes``
    The length of each test. The default is 1.5 participant sessions, from
    the timeline's time estimates, between one and 30 minutes. A test
    shorter than a session sees only the start of the study, and the
    report warns about it.

``--arrival-minutes``
    Spread the bots' arrivals over this many minutes, for a study whose
    participants arrive gradually. By default they all arrive within
    seconds, as when a study opens many places at once.

``--time-factor``
    A multiplier on the timeline's time estimates. ``1`` (the default)
    roughly matches real participants; ``0`` makes bots go as fast as
    possible, which loads the server far more than people do.

``--bot-processes``
    The number of processes running the bots (see
    :ref:`performance_testing_bot_processes`). The default, ``auto``, adds a
    process per 250 bots.

See ``psynet performance-test local --help`` for the rest.

Reading the results
-------------------

The main numbers are the response times for ``/timeline`` and ``/response``:
the median is the typical delay, and the 95th percentile is what the slowest
participants experience. *Bot outcomes* counts how each bot ended:
participants that the experiment failed, for example at a prescreen or when
a wait timed out, are under *Failed by the experiment*, and *Bot errors*
lists errors such as ``HTTP 500 on /response``. Other sections cover
runtimes, busy chains, requests answered busy or stale (which bots retry),
wait pages, async job queue waits and worker use, and how the database grew.
*Start-up vs steady state* splits the measures at the moment the first bot
finishes, because a study's opening burst is often its hardest moment.

Response times are measured inside the server, so they leave out time that
requests wait for a free web process. When the CPU is fully used that wait
grows quickly, so also watch request errors and the server's CPU.

The bots fetch pages and submit answers without a browser, and they run the
server-side work that answers trigger, such as async jobs. At a timeline
hold they poll every ``check_interval`` seconds, as a browser's fallback
does. They don't load static files or media, call custom routes from page
JavaScript, open websockets or go through the server's web proxy or
Cloudflare tunnel. If an experiment leans on these, also try it with real
browsers.

Bots don't open websockets, so the tests don't measure how many participants
can wait at once. A participant on a waiting page, such as a barrier or
:func:`~psynet.page.wait_while`, keeps a websocket open, and the web
process that accepted it holds a Redis connection and about two open files
for it. In one test on the server described in :ref:`choosing_server_size`,
1,000 participants waiting at once made no measurable difference to
response times. At about 2,000, a few web processes reached their limit of
1,024 open files and refused new websockets and ordinary requests.
`Dallinger#10102 <https://github.com/Dallinger/Dallinger/pull/10102>`_
raises that limit. Without `Dallinger#10052
<https://github.com/Dallinger/Dallinger/pull/10052>`_, which gives
websockets their own Redis connections, Redis requests already failed with
about 500 participants waiting. Neither is released yet.

If response times are high, profile the database queries with ``psynet test
local --sql-profile``; see :doc:`/test/sqlalchemy_profiling`.

.. _performance_testing_capacity:

Finding the server's capacity
-----------------------------

``--n-bots auto`` searches for the largest number of bots the server
handles well:

.. code-block:: bash

    psynet performance-test ssh --app my-experiment-perf --n-bots auto

A test passes if:

- at most 0.1% of ``/timeline`` and ``/response`` requests fail, and at
  most 1% of bots;
- at most 1% of those requests are answered busy or stale (HTTP 503 or 409);
- their 95th-percentile response time is under ``--max-p95-ms`` (default
  500);
- high-priority async jobs wait under ``--max-queue-p95-s`` (default 5 s)
  for a worker, at the 95th percentile;
- at most 1% of participants are failed for waiting too long, and at most
  1% get fewer trials because every chain was busy.

A single stray error doesn't fail a test. Low-priority async jobs, which
participants don't wait for (see :ref:`async_job_priority`), never fail a
test. If participants do wait for an
:meth:`~psynet.trial.main.Trial.async_post_trial` job some other way, for
example through a page that shows its result, set
``async_post_trial_priority = "high"`` on the trial class so that the
test judges its queue wait.

The search starts at 10 bots, doubles until a test fails, then narrows
the gap to within 10%; it stops at 2,000. Each search test lasts about one
session, at most 5 minutes, so a search of a 12-minute study takes about an
hour. It then runs a *validation test* at the recommended number, 80% of
the largest passing test, with arrivals spread over a session and lasting
two sessions (at most an hour), so that it reaches the study's steady
state. ``--no-confirm`` skips it. For a study longer than about half an
hour, also run a long test of the recommended number by hand with
``--n-bots N --arrival-minutes M``.

The summary at the end tabulates the tests and gives the verdict. For
example, from a static rating study on an SSH server (some rows left out)::

    PERFORMANCE TEST SUMMARY
    dog-rating on rr-pc02.student.mus.private.cam.ac.uk: 11 tests, 59 min
    Limits checked: p95 response time under 500 ms, at most 0.1% of requests failing, at most 1% of bots failing.

       Bots     Bots                              p95    Median      Failed     Failed      Bots
    at once  started  Length  Result  Req/s  response  response    requests       bots  finished
    ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
         10       10   3 min  pass      2.4     63 ms     27 ms           0          0         -
        480      480   3 min  pass     97.0     74 ms     32 ms           0          0         -
        520      520   3 min  pass    103.0     81 ms     33 ms           0          0         -  largest passing
        560      570   3 min  FAIL    110.5     91 ms     36 ms           0  10 (1.8%)         -
        640    1,271   3 min  FAIL    109.2    113 ms     37 ms  17 (0.09%)  631 (50%)         -
        416      849  23 min  pass     90.2     76 ms     29 ms           0          0       433  validation test

      Bots finished is - where the test was shorter than one participant session (11 min), so no bot could finish.

    Recommended: at most 416 participants at once.
      To enforce it, set max_concurrent_participants = 416 in Experiment.variables.
    Largest passing test: 520 bots at once. At 560, 10 of 570 bots (1.8%) failed, over the 1% limit.
      Errors at 560: 5 x HTTP 500 on /participant_status, 3 x OperationalError, 2 x HTTP 500 on /response.
    Validation test: 416 bots (80% of 520), arriving over 11 min, ran for 23 min and passed.

Nothing holds participants to the recommended number unless the study
enforces it. With the ``generic`` or ``hotair`` recruiter, the summary
suggests the ``max_concurrent_participants`` setting that does so (see
:ref:`limiting_simultaneous_participants`); with other recruiters it leaves
that line out.

*Notes* follow with advice, for example on errors, worker processes and
database growth. If the validation test fails, the summary suggests a lower
number and the command to check it. When search tests and a long test with
spread-out arrivals disagree, trust the long test. For rough capacities of
common server sizes, see :ref:`choosing_server_size`.

Some failures say more about the design or the test than the server, and
then the summary reports the largest passing test but recommends no number:

- *Wait timeouts* can come from the design, such as a short
  ``max_wait_time`` or too few participants to fill groups and chains.
  In a group experiment (see :doc:`/code/multiplayer/synchronization`),
  the test itself causes them when the number of bots isn't a multiple of
  the group size, because the bots left over wait until a running group
  finishes. Test multiples of the group size, or, with ``--n-bots auto``,
  give the copy you test a ``max_wait_time`` longer than a session. For
  the same reason the test doesn't show how many participants a
  recruitment rate loses at the grouper; see the advice on
  ``max_wait_time`` in :doc:`/code/multiplayer/synchronization`.
- *Limits of the test*: the bots couldn't start fast enough (fewer than 90%
  of them were active at once), their processes fell behind, or PostgreSQL
  ran out of connections for them. The processes running the bots create
  each bot's participant themselves, which limits how fast they start new
  bots; more ``--bot-processes`` help.

Run the search with ``--time-factor 1`` and at the length participants will
take. When bots finish within seconds, the test mostly measures how fast
bots are created. An abridged copy that keeps the heavy pages can help a
search of a long experiment; then confirm with a long test of the full one.

With ``--json-output``, the file is rewritten after each test, so a run that
crashes or that you interrupt keeps the tests that finished (see
:ref:`performance_testing_saving_results`).

.. _performance_testing_async_workers:

Async workers
-------------

Async jobs run in worker processes, separate from the web server. Two
config variables (see :doc:`/reference/configuration`) set how many run at
once:

- ``worker_processes`` (default 1): the number of worker processes, the
  ``worker_N`` containers on an SSH server or the worker dynos on Heroku.
  It replaces ``num_dynos_worker``.
- ``worker_greenlets_per_process`` (default 20): how many jobs each process
  runs at once.

Jobs in one process only overlap while they wait, for example on a web API
or the database. A CPU-heavy job, such as audio analysis in Python, blocks
the other jobs in its process: in the ``async_codeblock`` demo, one process
finished about 14 one-second jobs a second when they slept, but only about
one a second when they computed. For CPU-heavy jobs, such as tapping
experiments that analyse recordings with REPP, set
``worker_greenlets_per_process = 1`` and plan on about one worker process
per CPU core. On SSH servers the workers get a low CPU priority, so they
don't slow down participants' pages.

The summary estimates ``worker_processes`` from the steady state of one
test, aiming to keep the workers about 70% busy at the recommended number
of participants, and suggests ``worker_greenlets_per_process = 1`` when
the jobs are CPU-heavy. For example, a tapping study with 43 s of audio
analysis per 13-minute session gets::

    In the 130-bot test, jobs that participants wait for waited too long for one of the 10 worker processes.
    Recommended settings for 96 participants at once:
        worker_processes = 10
    In the 96-bot validation test, the 10 worker processes were busy 55% of the time. Keep the current 10 (the load needs about 8). To go above 96, raise worker_processes above 10 and test again.

The settings are in ``config.txt`` form. ``(minimum)`` marks an estimate
from workers that were saturated, and ``(all the cores left)`` a number
that uses every core, so going higher needs a larger server or cheaper
jobs. There is no estimate if the test had no steady state or fewer than
20 worker jobs finished in it. The ``recommend_workers`` docstring in
``psynet/perf_test/results.py`` gives the formula.

.. _performance_testing_database_size:

Database size
-------------

Some queries slow down as the tables grow: in one static rating study, the
same 208 bots got a 95th-percentile response time of 0.2 s with 100,000 to
150,000 trials in the database and 7 s with about 200,000. A test on a
fresh database therefore measures the start of a study.

Each test reports the rows in the growing tables before and after it, and
the summary warns when the database grew by more than half. Compare those
rows with what the study will collect. If it will collect much more, test
with that much data (see :ref:`performance_testing_reset`), or run a long
test that ends near the planned total; response times that rise steadily
during it point to a query to profile.

To test with real data, for example from a pilot, deploy a performance-test
app from its export (see :doc:`/deploy/reference/deploy_from_archive`) with
``performance_test_app = true`` in ``config.txt``, and run
``performance-test ssh`` on it with ``--force`` from the experiment's
directory; each run updates the app's code from that directory, keeping the
pilot's database.

.. _performance_testing_server:

Testing on a server
-------------------

A local test shares your computer's CPUs between the bots and the server.
To test a real server, run the test over SSH from the experiment directory,
naming a new app for it:

.. code-block:: bash

    psynet performance-test ssh --app my-experiment-perf --n-bots 50 --duration-minutes 10

The bots run inside the app's web container and send their requests
straight to the experiment server, skipping its web proxy and any
Cloudflare tunnel. They take a little of the server's CPU (about half a
core for 480 bots), but a capacity search loads the whole machine, so on a
shared server check with the other users first. Keep your computer
connected until the run ends; Ctrl-C stops the test on the server.

.. _performance_testing_server_app:

Apps for performance tests
~~~~~~~~~~~~~~~~~~~~~~~~~~

Performance tests fill the database with bots and may reset it, so they
only run on apps that ``performance-test ssh`` deployed for them. If the
server has no app named ``--app``, the command first deploys the experiment
under that name in debug mode, taking the same ``--server``, ``--dns-host``,
``--ingress``, ``--use-local-psynet``, ``--use-local-dallinger`` and
``--yes`` options as ``psynet debug ssh``. Like ``psynet debug ssh``, that
first deploy resets your local debug database. Bundled demos don't pin
PsyNet, so test them with ``--use-local-psynet`` (see
:doc:`/code/project/using_local_psynet_and_dallinger`). Only bots take part,
so the experiment needn't have a consent page.
On a private network, such as a lab computer, use ``--ingress cloudflare``.

The app's config is marked with ``performance_test_app = true``. Every
later run updates the app in place from the current directory before
testing, so it always tests your current code, and keeps its database.
An update doesn't deposit new assets, so destroy the app if you add assets
or want a fresh launch. The app stays on the server
after each run, so that you can look at its dashboard and logs, and the
command prints how to destroy it when you're done:

.. code-block:: bash

    psynet destroy ssh --server my-server --app my-experiment-perf

Runs refuse apps without the mark, such as ones deployed with ``psynet debug
ssh``, and live deployments refuse the mark. They also refuse a database
with participants that bots didn't create, live mode and recruiters that can
bring real participants. If the experiment isn't collecting real data, for
example after your own walkthrough, add ``--force``.

.. _performance_testing_reset:

Starting every test from the same data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default each test adds its bots' data to the database, so later tests in
a run see more data. ``--reset-database`` starts every test from the same
database instead:

.. code-block:: bash

    psynet performance-test ssh --app my-experiment-perf --reset-database --n-bots auto

PsyNet snapshots the database before the first test and restores it before
each later one, restarting the app's containers other than PostgreSQL,
Redis and the front door. At the end it restores the database to how the
run found it and drops the snapshot. If a restore fails, the command exits
with an error, keeps the copy and names it; destroy the app and run again
to recover. Each copy needs free disk space of twice the database's size,
which PsyNet checks first. Uploaded files stay in the asset storage. With
classic ingress, apps share one PostgreSQL server, so a run that is killed
can leave ``*_snapshot_*`` or ``*_baseline_*`` databases that ``psynet
destroy ssh`` doesn't remove; drop them with ``docker exec
dallinger-postgresql-1 sh -c 'dropdb -U "$POSTGRES_USER" <name>'``.

To test with the amount of data the study will reach, pre-fill the database:

.. code-block:: bash

    psynet performance-test ssh --app my-experiment-perf --prefill-participants 1500 --n-bots auto

This implies ``--reset-database``. Bots fill 1,500 participants' data
through the experiment's own routes before the snapshot, and the database
is restored afterwards, so each run pre-fills again. That takes time: about
an hour for 1,500 participants at a few hundred requests a second.

.. _performance_testing_bot_processes:

Processes running the bots
--------------------------

The bots run as threads in the ``performance-test`` process, so they share
module-level state and the experiment instance, as in :ref:`parallel tests
<parallel_bot_tests>`. One process sends at most a few hundred requests a
second, so larger tests spread the bots over several processes
(``--bot-processes``). Each process checks how late its threads run; a test
in which they fell more than 50 ms behind counts as a limit of the test,
and the summary suggests more processes. Over SSH, the bot processes run on
the experiment server, so ``auto`` uses at most one per four cores.

.. _performance_testing_saving_results:

Saving results
--------------

``--json-output results.json`` writes the full results and the run's
options to a file. To record the results in the experiment's audit, use
``psynet audit performance-test``, which runs locally and writes
``audit/artifacts/performance.json`` for the audit's *Performance test*
section.

In the ``--json-output`` file, each test's entry has these fields:

.. autoclass:: psynet.perf_test.results.PerformanceTestResult
    :members:
    :member-order: bysource
    :exclude-members: from_dict, steady_state_s

A typical sequence is a local sweep to see how response times grow with
load, then more worker processes or faster queries where needed, then a
capacity search (``--n-bots auto``) on the real server to choose how many
participants to run at once.

.. _limiting_simultaneous_participants:

Limiting simultaneous participants
----------------------------------

A study shared through a public link, such as a citizen-science study, can
attract more visitors at once than the server can serve. Past that point
every participant's pages slow down, including those of people who are
already halfway through. To protect them, cap the number of active
participants with the experiment variable ``max_concurrent_participants``:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        variables = {"max_concurrent_participants": 150}

Newcomers over the cap see a message on the start page saying that many
people are taking part. The page retries every 20 to 40 seconds and lets
them in once there is space. People who are already taking the study, or
who return to it, are never refused.

A participant counts towards the cap while they are working and have
joined or submitted a page in the last 10 minutes. People who close the tab
stop counting once that time passes. Simultaneous arrivals can overshoot the
cap by a few participants.

Choose the cap with a capacity search on the real server (see
:ref:`performance_testing_capacity`): its summary recommends a number, such
as ``max_concurrent_participants = 416``, with headroom below the largest
passing test.

Bots from ``psynet test`` and ``psynet performance-test`` create their
participants directly rather than through the start page, so the cap never
holds them back; a performance test measures the server, not the cap. They
do count towards it, though, so while bots are running, a low cap can keep
people who use the start page waiting.

PsyNet reads the cap from the experiment's variables each time a newcomer
arrives, so experiment code can change it while the study runs, for example a
code block that sets ``experiment.var.max_concurrent_participants = 80``.
There is no dashboard control or command for changing it by hand yet; to use
a different fixed cap, change ``variables`` and redeploy. To measure load
differently, override
:meth:`~psynet.experiment.Experiment.is_at_capacity`. For example, if some
pages run longer than 10 minutes without a submission (such as a long
video), count participants as active for longer:

.. code-block:: python

    from psynet.capacity import count_active_participants

    class Exp(psynet.experiment.Experiment):
        variables = {"max_concurrent_participants": 150}

        def is_at_capacity(self):
            limit = self.var.max_concurrent_participants
            return limit is not None and count_active_participants(1800) >= limit

The method runs every time a newcomer tries to start, including each retry
from the start page, so keep it cheap. After it reports the study as full,
each web process skips it for 2 seconds. People already waiting are let in at
their next retry, up to 40 seconds after the cap is raised. Use it only for
load: newcomers are told that many people are taking part and retried
automatically, which would mislead them if the study were closed for another
reason.

The cap and the method only work with the ``generic`` and ``hotair``
recruiters, and the recruiter must be named in ``config.txt`` or
``Experiment.config``; launching fails otherwise.
Prolific and CINT participants have accepted a place, so they should not
be kept waiting. With Prolific, ``initial_recruitment_size`` already roughly
limits how many people take part at once, because PsyNet opens a new place
only when someone finishes.
