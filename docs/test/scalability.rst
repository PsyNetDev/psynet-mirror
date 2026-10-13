.. _performance_testing:

===================
Testing scalability
===================

``psynet performance-test`` keeps a target number of bots active on a running
experiment and reports response times, throughput and queue delays.

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
jobs, such as asset deposits, which run in a thread of the process that
enqueued them, usually the web process; they skip the worker queues, so
their priority is ``-``. A CPU-heavy worker job keeps a CPU core busy while
it runs, so as load grows it needs more worker processes
(``worker_processes``) and a server with a core for each. A CPU-heavy web
job slows the web process instead, and more worker processes do not help
it. An I/O-bound job mostly waits, for example on an API call, and does not
need more cores. If no async jobs finished, PsyNet logs
``No async jobs finished.`` instead. Per-job values are in the ``cpu_time``
column of ``database/async_job.csv`` in the export; see
:class:`~psynet.async_job.AsyncJob` for how it is measured. The
:doc:`/skills/plan-server-resources` Agent Skill turns these numbers into a
worker estimate. Confirm the estimate with a performance test.

Running a test
--------------

From the experiment directory:

.. code-block:: bash

    psynet performance-test local

This starts a local server, keeps ``Experiment.test_n_bots`` bots (default 1)
active for about one and a half participant sessions (see
``--duration-minutes`` below), prints a report, and shuts the server down. Like
``psynet test local``, the server gets a free port, a database and a Redis
server of its own, so local debug servers keep running (see
:doc:`/developer/running_tests`). It prints the paths of the server and bot
logs, which go to a ``psynet-performance-logs-<user>`` folder in the temporary
directory; it keeps the 20 most recent of each. For a heavier load,
ask for more bots and a longer run:

.. code-block:: bash

    psynet performance-test local --n-bots 25 --duration-minutes 5

To compare several levels of load, pass a comma-separated list. PsyNet runs
one test per value and prints a summary comparing them:

.. code-block:: bash

    psynet performance-test local --n-bots "5,10,20,40"

Every bot and server process holds PostgreSQL connections, and all local
experiments and test sessions share one PostgreSQL server, whose
``max_connections`` is 100 by default. A run with a few hundred bots, or
several runs at once, can exceed it: PostgreSQL then refuses connections with
"sorry, too many clients already". Run fewer bots at once, stop other local
experiments, or raise ``max_connections`` (see
:doc:`/developer/running_tests`).

To use a server that is already running (for example from ``psynet debug
local``), add ``--existing``. A ``psynet debug local --legacy`` server stops
itself once the experiment reports that it is complete, which can happen
between bots when recruitment has closed. Start it with
``PSYNET_PERFORMANCE_TEST=1 psynet debug local --legacy`` to keep it running;
``psynet performance-test local`` does this for the server it starts. The
default ``psynet debug local`` server does not stop itself.

Local results show how the experiment copes on your computer. To choose
how many participants to run at once, measure the deployment server with
``psynet performance-test ssh`` (see below).

Controlling the load
--------------------

``--n-bots``
    The number of bots to keep active. PsyNet starts them after the first bot
    initializes and replaces bots as they finish. Defaults to
    ``Experiment.test_n_bots``.

``--duration-minutes``
    The length of each test, including the time bots take to start. By
    default a test lasts 1.5 participant sessions, rounded up to whole
    minutes: long enough for bots to finish and be replaced, so that the test
    sees the study's steady state as well as its start. A session is the
    experiment's estimated duration (from the timeline's ``time_estimate``
    values, shown in the suite header) times ``--time-factor``. The default
    is at most 30 minutes, so that a test of a long study stays practical,
    and at least ``Experiment.test_duration_minutes`` (one minute). A test
    shorter than one session sees only the start of the study, before any
    bot finishes, and the suite warns about it.
    With ``--n-bots auto`` the search's tests are shorter by default (see
    :ref:`performance_testing_capacity`).

``--stagger``
    The average delay, in seconds, between starting bots, so that they arrive
    at random intervals as real participants do. Defaults to
    ``Experiment.test_parallel_stagger_interval_s`` (0.1 s).

``--arrival-minutes``
    Spread each test's bots evenly over this many minutes after the first
    bot starts, instead of starting them ``--stagger`` seconds apart: with
    ``--n-bots 100 --arrival-minutes 10`` a new bot arrives every 6 seconds.
    Use it when participants will arrive gradually; the default, where
    every bot arrives within seconds, matches a study that opens many places
    at once. With ``--n-bots auto`` only the validation test uses the
    window; the search's tests stay short, with the bots starting together
    (see :ref:`performance_testing_capacity`). Bots that replace finished
    ones still start after ``Experiment.test_parallel_stagger_interval_s``,
    so ``--arrival-minutes`` can't be combined with ``--stagger``. Otherwise
    the window must be shorter than ``--duration-minutes``; without
    ``--duration-minutes`` it is added to the default test length.

``--time-factor``
    A multiplier on the time estimates in the timeline, controlling how fast
    bots work through the experiment. ``1`` (the default) roughly matches real
    participants; ``0`` makes bots go as fast as possible. Each bot's pace varies
    randomly around this value, from 0.7 to 3 times it, because people rarely
    work much faster than the time estimates. Above ``0``, bots also never
    submit a page before a participant could: a recording page takes at least
    its recording's ``duration``, and an audio meter at least its
    ``min_time`` (see :attr:`~psynet.timeline.Page.min_duration`). Bots don't
    know how long media prompts play, so they can still leave those early.

``--bot-processes``
    The number of processes to run the bots in (see
    :ref:`performance_testing_bot_processes`). ``auto``, the default, uses one
    process per 250 bots, up to one per four CPU cores, so tests of fewer than
    250 bots run in a single process. With ``--n-bots auto`` it plans for the
    largest count the search may test.

For example, to model 50 participants arriving over five minutes and working
at a realistic pace:

.. code-block:: bash

    psynet performance-test local --n-bots 50 --arrival-minutes 5 --time-factor 1 --duration-minutes 20

Reading the results
-------------------

The main numbers are the response times for ``/timeline`` and ``/response``:
the median shows the typical delay, and the 95th percentile shows the delay
that the slowest participants experience. The report also shows:

- **Bot outcomes**: how many bots started and how each ended. *Completed
  successfully* counts bots that finished the experiment without the
  experiment failing their participant. *Failed by the experiment* counts
  participants that the experiment failed, for example at a prescreen or
  when a wait timed out (see :meth:`~psynet.participant.Participant.fail`).
  They often still end ``approved`` after the unsuccessful end; ``failed``
  is what matters, so check this line as well as the first. A breakdown lists the most common failure reasons, built from the
  participants' failure tags, and marks those that mean the participant
  waited too long. *Bot error or other status* counts bots that raised an
  error, or whose participant ended with another status such as
  ``returned``. *Stopped at the end of the test* counts bots still taking
  the experiment when the test ended. A bot stopped there while waiting at
  a hold whose time limit had passed, but which it had not checked again,
  is not yet counted as failed. *Bot error before joining* counts bots
  that raised an error before their participant was created. The *Bot
  errors* list below counts every bot that raised an error, including
  those whose participant the experiment failed, so its total can exceed
  the error rows above.
- **Bot runtimes**, separately for each of these outcomes, and **trials per
  bot** (for bots that completed successfully). Below the trials, a line for
  each chain trial maker says how many bots got fewer trials because every
  chain was busy, for example ``23 of 150 bots started (15%) got fewer
  trials in main_chain because every chain was busy; median 41 of 60
  trials.`` Bots started include those that replaced bots that finished.
  Chains that are busy only with their last trials don't count, because
  they would have nothing left to give.
- **Request metrics**: total requests, errors and throughput. A
  *Busy/stale responses (409/503)* line appears when ``/timeline`` or
  ``/response`` answered with HTTP 503, which PsyNet sends when the
  experiment is busy, or HTTP 409, which it sends when a page went stale.
  Bots retry those that PsyNet marks as busy or stale. These responses are
  not counted as request errors.
- **Time on wait pages per bot**, for experiments with wait pages: the
  total time each bot that completed successfully or was failed by the
  experiment spent waiting. Failed bots are included because those that
  timed out waited longest.
- **Async job times**: for experiments with async jobs, such
  as audio analysis, the execution time, CPU time and time spent waiting in
  the queue, for each label and :ref:`priority <async_job_priority>`, with
  the number of worker processes and how many jobs they can run at once.
  If fewer worker processes were running at the end of the test than
  ``worker_processes`` configures, the report warns and names both
  numbers. A high queue share, highlighted in yellow or red, means more worker
  processes are needed; see :ref:`performance_testing_async_workers`. With a
  steady state, the report also says how busy the worker processes were. Below
  the table, the report counts the jobs of each priority still queued when
  the test ended.
- **Start-up vs steady state**: the request count, 95th-percentile response
  time, request errors and the 95th-percentile queue wait of high- and of
  low-priority async jobs, separately for the start-up and the steady
  state, with the low-priority jobs still queued at the end of each. A
  finished wait counts in the phase in which the job started. A job still
  queued when the start-up ended also counts in the start-up's queue wait,
  with the time it had waited so far. The start-up lasts until the first bot
  completes the experiment: until then every bot is in its first session,
  as when a study opens and its first participants arrive together, so
  queues fill up and slow pages are hit by everyone at once. The steady
  state is the rest of the test, when bots finish and are replaced at
  different points of the experiment. The table appears when the steady
  state lasts at least a minute; otherwise the report says how far the
  test got.
- **Database rows**: the rows in the tables that grow as a study collects
  data (participants, trials, responses, nodes, networks, async jobs
  and assets), before the test and after it. See
  :ref:`performance_testing_database_size`.

Response times are measured inside the server, from when a web worker starts
handling a request until it finishes. They do not include time that a request
spends waiting for a free worker. When the server's CPUs are fully used, that
waiting grows faster than the reported times, so also watch the server's CPU
use and the number of request errors.

The bots fetch pages and submit answers without a browser. They also run
the server-side work that answers trigger, such as async jobs, and
they wait at timeline holds: with a ``--time-factor`` above 0 they check the
hold every ``check_interval`` seconds, as a browser's fallback poll does. The
results leave out everything else a browser does, including static files and
media, requests to custom routes from page JavaScript, and websockets, which
browsers keep open at timeline holds and in live multi-participant pages. If
an experiment leans on these, also test it with real browsers. The summary
of every run ends with a *Not measured* line as a reminder: uploads over
participants' own networks (the bots upload from next to the server), media
downloads and bandwidth, the front door (the server's web proxy or a
Cloudflare tunnel) and browser rendering.

If response times are high, profile the database queries with ``psynet test
local --sql-profile``; see :doc:`/test/sqlalchemy_profiling`.

.. _performance_testing_capacity:

Finding the server's capacity
-----------------------------

``--n-bots auto`` searches for the largest number of bots the server handles
well, so you don't have to guess a list of counts:

.. code-block:: bash

    psynet performance-test local --n-bots auto --time-factor 1

A test passes if these stay within their limits:

- the share of ``/timeline`` and ``/response`` requests that fail, at most
  0.1% (one failed request is always allowed), and the share of bots that
  fail, at most 1%. A single stray error doesn't fail a test, however short,
  but the summary still reports any errors in the largest passing test. Busy
  (HTTP 503) and stale-page (HTTP 409) responses don't count as request
  errors. Bots retry those that PsyNet marks as busy or stale, and a bot
  that gives up, or gets a 409 or 503 it doesn't retry, counts as a failed
  bot;
- the share of ``/timeline`` and ``/response`` requests answered as busy or
  stale, at most 1% (ten are always allowed). Bots retry these responses,
  so without this limit a server stuck on lock contention could pass with
  no errors and short response times. The allowance covers the occasional
  contention at timeline holds and in synchronized groups;
- the 95th-percentile response time for ``/timeline`` and ``/response``,
  together and for each of them, limited by ``--max-p95-ms`` (default 500);
- the 95th-percentile time that high-priority async jobs wait in the queue
  for a worker, limited by ``--max-queue-p95-s`` (default 5). Participants
  often sit on a wait page during this time, so it matters as much as
  response time. Jobs still waiting when the test ends count with the time
  they have waited so far, so a queue that never drains fails the test.
  Local jobs, which have no priority, count as high priority. Participants
  don't wait for low-priority jobs, such as analyses of trials without
  feedback (see :ref:`async_job_priority`), so a backlog of these, which
  often builds up in the start-up, never fails a test. When their queue
  wait exceeds the limit, the summary reports it and how many were still
  queued at the end;
- the share of bots whose participants the experiment failed for waiting
  too long, at most 1%. These are participants failed when a
  :func:`~psynet.page.wait_while` (including async code blocks that wait),
  a barrier, or a ``while_loop`` with ``max_loop_time`` (such as waiting
  for a trial) timed out, or when a group barrier timed out between
  barriers. In a test that has such failures, members of a sync group
  failed because the group fell below its minimum size count too, because
  they usually follow from them. In a real study those participants would
  be lost, so wait timeouts count as failures at any bot count, and
  experiments should be designed to avoid them, for example with a longer
  ``max_wait_time`` or enough participants to fill groups and chains. At
  high bot counts they can also mean the server is too slow. Because they
  may come from the design, when wait timeouts are all that the smallest
  failing count exceeded, the summary gives the largest passing test, says
  the limit wasn't found and recommends no number of participants. Other failures, such as
  prescreens, are part of the design: the summary reports them but they
  don't count against the limits;
- the share of bots that got fewer trials in a chain trial maker because
  every chain (or node, in a static trial maker) they could take was busy,
  at most 1% for each trial maker, set with
  ``--max-busy-early-finish-rate`` (default 0.01). One such bot per trial maker
  is always allowed, so that a single busy chain doesn't fail a small test. With the default
  ``wait_for_networks=False``, a participant who finds every eligible chain
  awaiting an async job or out of trial capacity finishes the block
  early instead of waiting. Static trial makers don't limit trials per node
  during selection, so they only do this when every node awaits an async
  job. The participant is not failed, so the test
  results show these bots under *trials per bot* instead, with their median
  number of trials and the trial maker's ``expected_trials_per_participant``.
  Unlike wait timeouts, this sets the largest passing test and the
  recommended number of participants: chains are busy more often the more
  participants take part at once, so fewer participants reduce it.
  Setting ``wait_for_networks=True`` or adding chains reduces it too, and
  may allow more participants at once. How participants arrive can make
  busy chains more or less common, so judge the recommended number by the
  validation test that ``--n-bots auto`` runs, whose bots arrive over a
  session.

The limits apply to the whole test, start-up included, because a real study
also has a start-up burst: recruiters often release many places at once when
a study opens. When the smallest failing count exceeded the response-time,
request-error or queue limits only in its start-up, the summary says so. If
your participants will arrive gradually, test that with ``--arrival-minutes``
rather than relying on the steady state alone.

The search's tests are short and their bots arrive together, so for most
studies they see only the start-up. In an experiment with async jobs,
such as audio analysis, or with long timeline holds, every bot reaches each
job and each hold at the same moment, so queue waits are longer than
when participants arrive spread out, and the search underestimates how
many participants the server can handle. The search therefore ends with a
*validation test*: it runs the recommended number of participants (80% of
the largest passing test), with bots arriving
evenly over one participant session and the test lasting two sessions, at
most an hour, so that the test reaches its steady state. A study over 30
minutes gets less than two sessions, and one over about an hour no steady
state, so for long studies also run a long test of the recommended number by hand. With your own
``--arrival-minutes``, the validation test uses that window instead of one
session and lasts a session longer, again at most an hour, or
``--duration-minutes`` if that is longer; the window must be shorter than
this longest validation test. The summary only confirms the recommended
number if the validation test stayed within the limits and reached its
steady state; one that never got there leaves it unconfirmed. If the test
exceeded the limits, the summary shows which limits the start-up and the
steady state exceeded, and recommends trying a lower number, scaled by how
far the test overshot its limits (but at least half the tested number),
with the command to validate it. A test that could not measure
the server, for example because the server stopped, no responses were
recorded or the bots couldn't start fast enough, leaves the recommendation unconfirmed without a suggestion. The
search does not run again. Add ``--no-confirm`` to skip the validation
test; it is always skipped with ``--time-factor 0``, whose pace isn't
realistic, when the experiment's estimated session length is unknown, and
when the search recommends no number.

Without ``--reset-database``, the validation test runs on the data that
the search tests left. If it fails after starting with much more data than
the largest passing test, the summary suggests rerunning with
``--reset-database`` before recommending a lower number.

The summary names the limit that a failing test exceeded. If the queue limit
is what failed the next count, the summary says how many worker processes
the server had; add more before settling for fewer participants. After a
confirmed recommendation it words this as how to go above that number.
The summary also checks whether the workers keep up in the long run, in one
test: the validation test if there was one, otherwise the largest passing
test, or the first failing test if none passed. It warns when the worker
processes were more than 85% busy in the steady state, or when the
low-priority backlog at the end of the steady state is at least twice the
backlog at the end of the start-up and at least 10 jobs longer. That doesn't
fail the test by itself, because participants don't wait for low-priority
jobs, but their results arrive later and later and the jobs keep the workers
busy. Whenever the queue limit or this check
fires, and whenever that test ran worker jobs in its steady state, the summary
estimates ``worker_processes`` for the recommended number of participants, or without one for that test's
bot count; see :ref:`performance_testing_async_workers`.

The search starts at 10 bots and doubles the count until a test fails, then
halves the gap between the largest passing and smallest failing counts until
they are within 10% of each other. It stops at 2,000 bots. For a server that
handles more than about 100 bots this takes 8 to 12 tests. By default each
search test lasts one participant session, rounded up to whole minutes, at
most 5 minutes and at least ``Experiment.test_duration_minutes``;
``--duration-minutes`` sets another length. A search of a 12-minute study
therefore takes 40 to 60 minutes, and its validation test another 24
minutes. The run prints its upper bound when it starts.

When bots fail, the report lists what went wrong, for example
``HTTP 500 on /response``. The request error count only includes errors that
the server managed to log, so a server that cannot reach its database shows
them under *Bot errors* instead.

The summary at the end of every run lists the tests by the number of bots
taking part at once (*Bots at once*), with the validation test last, whether
each passed the limits, and the measures that the limits check. Busy
responses, participants the experiment failed, busy chains and async queue
waits only appear when a test had them, in a second table under the first,
with the same rows; the limits line lists only the limits that apply. *Bots started* counts every bot that started during
the test, including bots that replaced earlier ones. *Failed requests* gives
a percentage of all requests and *Failed bots* a percentage of the bots
started; *Failed bots* counts every bot that raised an error. A measure is
red only if it broke its limit, so a failing test can show failures that
stayed within their limits uncoloured. Response times are in milliseconds
and queue waits in seconds. An empty cell shows ``-``: *Bots finished*
counts bots that completed the experiment, or shows ``-`` when a test was
shorter than one participant session, so that no bot could finish. The verdict follows: the recommended number of participants taking
part at once, the *largest passing test* and why the next count failed,
naming each measure, its value and its limit (when no test failed, the
verdict says the limit wasn't reached), and the *validation test* run at the
recommended number. Without a validation test, the recommendation is 80% of
the largest passing test. For example, from a capacity search of a static
rating study on an SSH server (some rows left out)::

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
    Largest passing test: 520 bots at once. At 560, 10 of 570 bots (1.8%) failed, over the 1% limit.
      Errors at 560: 5 x HTTP 500 on /participant_status, 3 x OperationalError, 2 x HTTP 500 on /response.
    Validation test: 416 bots (80% of 520), arriving over 11 min, ran for 23 min and passed.

Notes on the results, such as advice on errors and database growth, follow
under *Notes*. When standard output is a terminal, the summary is coloured
and its text wraps to the terminal's width; otherwise, as in a log file, it
is plain text with one line per paragraph. The tables are never wrapped.

For rough capacities of common server sizes, based on one test on a real
server, see :ref:`choosing_server_size`.

Run the search on the server you will deploy to, with ``--time-factor 1`` so
that bots work at a realistic pace; bots with ``--time-factor 0`` load the
server far more than people do. Each test's measurement window includes the
time bots take to start, so for steady results of a single bot count keep
the default ``--duration-minutes``, or at least one participant session. A test whose bots didn't all start within the
window counts as exceeding the limits, and the summary warns when starting
the bots took more than a quarter of the test, unless ``--arrival-minutes``
spread them out on purpose or a validation test passed.

With ``--json-output``, each result records the test's
``duration_minutes``, ``arrival_minutes`` and ``session_minutes`` (the
estimated session times ``--time-factor``), its ``startup_phase`` and
``steady_state_phase`` metrics, and per async job label and priority, in
``async_job_stats``, how long the jobs took, how much CPU they used
(``cpu_avg``) and how long they waited. ``queue_waits``, for the whole test
and for each phase, has an entry for each priority (``high``, ``low``) that
had jobs: the number of ``jobs`` that started, their ``q_delay_p95``, the
``backlog`` of jobs still queued at the end and how long the oldest of them
had waited (``oldest_queued_s``). ``n_rq_workers`` is the number of worker
processes running at the end of the test,
``configured_worker_processes`` the number ``worker_processes`` configures
and ``server_cores`` the CPU cores where the test ran (the web container's,
for ``performance-test ssh``). For a test with a steady state,
``worker_load`` records the worker jobs that finished in it (``jobs``), the
seconds worker jobs ran in it (``busy_s``), the finished jobs' CPU time as a
share of their run time (``cpu_share``) and the worker time per bot that
completed (``per_participant_s``).
The JSON flag ``confirmation`` marks the validation test,
and the options record ``confirmation_skipped`` with the reason it didn't
run. If resetting the database failed, ``reset_error`` gives the error
(see :ref:`performance_testing_reset`). The file is rewritten after each
test, so a run that crashes or that you interrupt keeps the tests that
finished; ``finished_at`` stays null until the run ends. When the search tests and a long test with spread-out arrivals
disagree, trust the long test.

The processes running the bots create each bot's participant themselves, so
they can only start new bots at a limited rate, which depends on the
experiment, the computer and ``--bot-processes``. The most bots they can
keep taking part at once
is roughly that start rate multiplied by how long each bot takes to finish
the experiment. A longer experiment, or a larger ``--time-factor``, keeps
more bots taking part at once. A test in which fewer than 90% of the
requested bots were ever taking part at the same time counts as exceeding
the limits. Bots that fail because PostgreSQL ran out of connections, or
because PgBouncer on an SSH server did ("no more connections allowed
(max_client_conn)"), count against the bot error limit too, but they also
point to the test: the bots open database connections in the processes
running them that participants' browsers don't. For PgBouncer, the summary
suggests raising its ``max_client_conn`` (`Dallinger PR #10051
<https://github.com/Dallinger/Dallinger/pull/10051>`__ raises it to 10,000
for SSH servers) or bounding the database connection pool. Bots that run late because their process is too busy (see
:ref:`performance_testing_bot_processes`) are a limit of the test too. These are limits of the test, not of the server, so when they are
the only limits the smallest failing
count exceeded, the summary gives the largest passing test, says the limit
wasn't found and recommends no number of participants. If no count passed,
it says no limit was found and why the test couldn't measure the server
at the smallest count, with advice on what held the test back. Response times, queue waits,
request errors and busy responses still fail a test that also had these
limits.

Test the experiment at the length participants will take it. When bots
finish within seconds, the test mostly measures how quickly bots are
created and replaced rather than a realistic load, so avoid testing
shortened versions of an experiment. The test doesn't reset the database, so later tests in a
sweep run against more data than earlier ones (see
:ref:`performance_testing_database_size`).

Bots don't open websockets, so the search doesn't measure how many
participants can wait at once. A participant on a waiting page, such as a
barrier or :func:`~psynet.page.wait_while`, keeps a websocket open, and the web worker that
accepted it holds a Redis connection for it. Redis allows 10,000 clients by
default, shared by the whole app, so about 10,000 participants can wait at
once on an SSH server. A web worker's open-file limit, often 1,024 with two
files per waiting participant, also limits it to about 500 per worker. This
needs a Dallinger release newer than 12.4; with 12.4 and earlier, a web
worker runs out of Redis connections once about 100 participants have waited
on it.

.. _performance_testing_async_workers:

Async workers
-------------

Async jobs run in worker processes, separate from the web server. Two
config variables (see :doc:`/reference/configuration`) set how many jobs run
at once:

- ``worker_processes`` (default 1) is the number of worker processes: the
  ``worker_N`` containers on an SSH server, the worker dynos on Heroku, and
  the local worker processes of ``psynet debug local --legacy`` and
  ``performance-test local``. It replaces ``num_dynos_worker``.
- ``worker_greenlets_per_process`` (default 20) is how many jobs each
  worker process runs at once with gevent.

The async section of the test results shows both, for example ``2 worker
processes, up to 40 jobs at once``. Jobs in the same process only overlap
while they wait, for example on a web API, the database or ``time.sleep``.
A job that keeps the CPU busy, such as audio analysis in Python, blocks the
other jobs in its process until it finishes. In the ``async_codeblock``
demo, one worker process finished about 14 one-second jobs per second when
they slept, but only about one per second when they computed.

So for experiments with CPU-heavy async jobs, such as tapping
experiments that analyse recordings with REPP, set
``worker_greenlets_per_process = 1``, so that a busy process doesn't take
jobs that a free one could run, and plan on about one worker process per CPU
core. Workers start high-priority jobs first, but a long low-priority job
still occupies its worker until it finishes. On SSH servers the worker
containers get a low CPU priority, so that a busy worker doesn't slow down
participants' pages, but they still use every core that is free.

The summary estimates ``worker_processes`` for you from the steady
state of one test (see :ref:`performance_testing_capacity`), and each test's
async section shows how busy the worker processes were. With ``W`` worker
processes, ``R`` jobs running per process on average in the steady state and
the finished jobs' CPU time a share ``c`` of their run time:

- *Utilization.* With one job slot per process, ``U = R``. With more slots, a
  job's CPU time includes what the other jobs in its process used meanwhile,
  so ``c / max(R, 1)`` is the CPU share of each job. If that is at least 50%,
  the jobs are CPU-heavy: the summary suggests
  ``worker_greenlets_per_process = 1``, and sizes for each running job
  needing a process, ``U = R``, while reporting the processes as busy
  ``min(R, 1)`` of the time. Otherwise it keeps the configured slots, and a
  process is busy when its slots or its core are:
  ``U = max(R / slots, c × min(R, 1))``.
- *Steady state.* ``U × W × (participants / bots) / 0.7`` processes keep the
  workers 70% busy, leaving headroom for bursts and for jobs that slow down
  under load. Workers at least 95% busy couldn't show the full demand, so the
  estimate is then a minimum; with one slot per process it comes from the
  worker time per participant who completed, as
  ``participants × (worker time per participant) / (session length × 0.7)``.
- *Start-up burst.* When the queue limit failed the search's next count,
  the participants arriving together need about
  ``W × participants / (largest passing test)`` processes. This is optimistic once the cores run out, because jobs then
  slow down.
- *Current workers.* The summary suggests at least the processes the test
  had, and one more if the workers fell behind: more than 85% busy, or a
  growing low-priority backlog.
- *Cores.* The suggestion is at most the cores where the test ran less two
  for the web server and database, whose use the test doesn't measure, even
  if that is fewer than the test had. If the load needs more, the summary
  says the server lacks cores.

There is no estimate if no bot finished (so there was no steady state), if
the steady state lasted under a minute, or if fewer than 20 worker jobs
finished in it. Search tests are often shorter than a session, so a search
that skipped its validation test then names a longer test to run at the
cap, with ``--arrival-minutes``. When the estimate is lower than the
current processes, the summary still suggests keeping them, and says how
many the load needs. For example, a tapping study with 43 s of
audio analysis per 13-minute session, whose capacity search failed at 130
bots on queue waits and whose 96-participant validation test kept 10
single-slot workers 55% busy, gets::

    In the 130-bot test, jobs that participants wait for waited too long for one of the 10 worker processes.
    Recommended settings for 96 participants at once:
        worker_processes = 10
    In the 96-bot validation test, the 10 worker processes were busy 55% of the time. Keep the current 10 (the load needs about 8). To go above 96, raise worker_processes above 10 and test again.

The settings are in ``config.txt`` form. ``worker_greenlets_per_process`` is
only listed when it should change. ``worker_processes >= N (minimum)`` marks
an estimate from saturated workers, and ``(all the cores left)`` a number
that uses every core left, so going above the recommended number then needs a larger server
or cheaper jobs rather than more worker processes. The reason says what the test measured and
what set the number: the load, the current processes, one more than
processes that fell behind, or the cores.

.. _performance_testing_database_size:

Database size
-------------

How many participants a server can handle depends on how much data the
experiment has already collected, not only on how many take part at once. Some queries read
more rows as the tables grow: in one static rating study, the same 208
bots got a 95th-percentile response time of 0.2 s while the database held
100,000 to 150,000 trials and 7 s once it held 190,000 to 214,000. A test
on a fresh database therefore measures the start of a study, and a
recommendation found early in a study may not hold later.

Each test reports the rows in the tables that grow, before and after it,
under *Database rows*. By default the tests don't reset the database, so
every test adds the data its bots create, and a capacity search, whose bot
counts don't run in increasing order, compares counts at different sizes.
The summary warns when the database grew by more than half during
the tests (and by at least 10,000 rows; with ``--reset-database``, during
any one test), or when the largest passing and
smallest failing bot counts started with very different amounts of data,
and then suggests ``--reset-database``.

To read the numbers:

- Treat a recommendation as holding for about the amount of data the tests ran
  with. Compare the trial and participant rows with what the study will
  collect: the number of participants you plan to recruit, times the
  trials each one makes.
- If the study will collect much more, test with that much data (see
  :ref:`performance_testing_reset`), or run a long test that ends near the
  planned total, for example at the recommended number of participants. If
  response times rise steadily during that test, a query is getting slower
  as data accumulates; profile it with ``psynet test local --sql-profile``
  (see :doc:`/test/sqlalchemy_profiling`).
- If the database already holds data from earlier runs, its size can make
  a small study look worse than it will be. Relaunch the experiment to
  start again from an empty database.

.. _performance_testing_reset:

Starting every test from the same data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``--reset-database`` starts every test from the same database, so that the
tests of a capacity search differ only in load. This section describes
``performance-test local``; :ref:`performance_testing_server_reset` explains
what differs on a server.

.. code-block:: bash

    psynet performance-test local --reset-database --n-bots auto

Before the first test, PsyNet copies the experiment's database into a
snapshot database. Before each later test, it stops the experiment server,
drops the experiment's database and creates it again from the snapshot,
empties the async job queues and starts the server again. That takes a few
seconds, plus a few seconds per gigabyte of data, because PostgreSQL copies
the database's files. At the end it drops the snapshot. A test run only
ever drops the experiment's own database and its temporary snapshot. Kept pre-fill
snapshots (see below) are only dropped by ``psynet performance-test
snapshots``, whose ``--drop-all`` drops every pre-fill snapshot on this
computer. Files that the bots uploaded or
generated stay in the asset storage after a reset, because only the
database rows that refer to them are reset; they cost disk space but
nothing else.

The snapshot holds whatever the database held when the run started. If it
already held participants, for example from an earlier run, PsyNet warns
that every test starts from that data and says how to start from an empty
database.

If a reset fails after some tests have run, PsyNet stops the run, prints
the summary of the tests that completed and writes them to
``--json-output``, then exits with an error that names the reset failure.

Resetting drops the experiment's database, so these options only work in
the database that the isolated test environment creates for each
``performance-test local`` run by default, and drops when the run ends.
They refuse any other database, such as the ``dallinger`` database you
debug with. The isolated environment is skipped when ``CI`` or
``PSYNET_TEST_ENVIRONMENT=shared`` is set, so unset those to reset. The
PostgreSQL role must be allowed to create databases, as it already must be
for the isolated test environment (see :doc:`/developer/running_tests`).

Each copy needs disk space, so before one PsyNet checks that the disk
holding PostgreSQL's data has at least twice the database's size free. If
the space isn't free, PsyNet stops and says how much space the pre-fill
snapshots use. It can only check if the PostgreSQL role may read the
server's settings and the server's data directory is on this computer,
not in a container; otherwise it warns once and carries on.

To test with the amount of data the study will reach, pre-fill the
database before the first test:

.. code-block:: bash

    psynet performance-test local --prefill-participants 1500 --n-bots auto

This runs 1,500 bots through the experiment, 50 at a time and without
pauses, waits for their async jobs to finish, and then takes the
snapshot, so every test starts with 1,500 participants' data. The bots use
the same routes as participants, so the data is what the experiment itself
stores, but it takes time: at about 250 requests per participant, a few
hundred requests per second fill 1,500 participants in about an hour.
The pre-fill adds to whatever the database already holds, such as bots
from earlier tests, and the snapshot keeps it all; PsyNet warns when the
database isn't empty.

If any pre-fill bot raises an error, the run stops without keeping a
snapshot, because the data would differ from what participants leave.
Participants that the experiment fails by design, for example at a
prescreen, are only counted.

PsyNet keeps the pre-filled snapshot and prints its name, which comes from
a hash of the experiment's files and the PsyNet and Dallinger versions,
followed by the number of pre-fill participants. The files are those a
deployment copies, without the ones Git ignores, plus ``config.txt``,
``requirements.txt`` and ``constraints.txt`` where they exist. A later run
with the same files, versions and number of participants starts from that
snapshot instead of pre-filling again. PsyNet never changes a kept snapshot: to pre-fill again, drop it
with ``psynet performance-test snapshots --drop <name>`` and run the test
again. Any change to those files, even a comment, means a new pre-fill. If
a change can't affect the data, such as a fixed typo, start from the old
snapshot with ``--from-snapshot <name>``, which only warns that the code
differs.

If a run is interrupted after its pre-fill finished but before the
snapshot was taken, PsyNet still takes the snapshot as the run ends, so
the pre-fill isn't lost.

Pre-fill snapshots stay on the database server until you drop them; after
keeping a new one, PsyNet lists the others and their sizes. List them, with
their sizes and the experiment that made them, and drop them with:

.. code-block:: bash

    psynet performance-test snapshots
    psynet performance-test snapshots --drop psynet_prefill_0123456789ab_n1500
    psynet performance-test snapshots --drop-all

``--drop-all`` drops every pre-fill snapshot on this computer's PostgreSQL
server, whichever experiment made it.

To start from real data instead, for example from a pilot, export the
pilot with ``psynet export``, add ``performance_test_app = true`` to
``config.txt``, launch a new app from the export with ``psynet debug ssh
--app my-experiment-perf --archive export.zip`` (see
:doc:`/deploy/reference/deploy_from_archive`), remove the line from ``config.txt`` again, and
run ``psynet performance-test ssh --app my-experiment-perf`` (see
:ref:`performance_testing_server_app`). Every test then starts with at least
the pilot's data.

Locally, these options need the server that ``performance-test local``
starts, so they can't be combined with ``--existing``.

.. _performance_testing_server:

Testing on a server
-------------------

A local test is limited by your own computer, because the bots share its CPUs
with the server. The bots are cheap (see
:ref:`performance_testing_bot_processes`): on a four-core computer, 200 bots
working at a realistic pace used about a third of one core, against nearly
three cores for the server. To test a real server, run the test over SSH
from the experiment directory, naming a new app for it; PsyNet deploys the
experiment under that name in debug mode first (see
:ref:`performance_testing_server_app`). The bots then run inside the app's
web container and send their requests straight to the experiment server,
skipping the server's web proxy and any Cloudflare tunnel, so the test
measures the experiment itself. They still take a little of the server's
CPU (about half a core for 480 bots), and a capacity search loads the whole
machine, so on a shared server check with the other users first:

.. code-block:: bash

    psynet performance-test ssh --app my-experiment-perf --n-bots 50 --duration-minutes 10

Your computer runs the series of tests, or the capacity search, and the
server runs one test at a time and sends its results back, so keep your
computer connected until the run ends. Interrupting the run with Ctrl-C
stops the test on the server.

By default the test does not reset the database, so repeated runs
accumulate data (see :ref:`performance_testing_database_size` and
:ref:`performance_testing_server_reset`). Make
sure the app allows enough participants for the number of bots, and that
nobody else is using it during the test.

.. _performance_testing_server_app:

Apps for performance tests
~~~~~~~~~~~~~~~~~~~~~~~~~~

Performance tests fill the database with bot participants, and with
``--reset-database`` they drop it, so they only run on apps that
``performance-test ssh`` deployed for them, never on an existing
deployment. If the server has no app named ``--app``,
``performance-test ssh`` first deploys the experiment from the current
directory under that name, in debug mode, as ``psynet debug ssh`` would. It
takes the same ``--server``, ``--dns-host``, ``--ingress`` and
``--use-local-dallinger`` options. If the server is on a private network,
such as a lab computer, add ``--ingress cloudflare``: Let's Encrypt cannot
issue certificates for a private address, so classic ingress fails there.

The app's config marks it as a performance-test app with
``performance_test_app = true``, and records the hash of the experiment's
files and the PsyNet and Dallinger versions that it was deployed with (the
same hash that names pre-fill snapshots, see :ref:`performance_testing_reset`).
Each run reads both inside the app's web container. If the hash differs
from that of the experiment directory, the run first updates the app as
``psynet debug ssh --update`` does: it rebuilds and restarts the app's
containers but keeps its database, with the data of earlier tests, and its
pre-fill snapshots. The old snapshots no longer match the new hash, so a
run with ``--prefill-participants`` pre-fills again, adding to the data
already in the database, and keeps the old snapshots until you drop them.
The database keeps the tables of the earlier code, and
launch steps, such as creating networks, don't run again; if the change
needs them, destroy the app and let the next run deploy it again. Update
the app only through ``performance-test ssh``: ``psynet debug ssh
--update`` doesn't set ``performance_test_app``, so the app would lose its
mark.

If an app of that name exists but isn't marked, for example one you
deployed with ``psynet debug ssh`` or ``psynet deploy ssh``, every run
refuses it, as does ``psynet performance-test snapshots --app``; choose
another app name. Setting ``performance_test_app = true`` in ``config.txt``
yourself declares that the app's data is disposable: performance tests may
add to it, reset it and drop it. ``psynet deploy ssh`` and other live
deployments refuse to deploy with it set.

Runs also refuse a marked app whose deploy never finished launching the
experiment, for example because Dallinger's launch request timed out while
a new Cloudflare tunnel came up: its containers run, but the experiment
has no launch steps behind it. Destroy it with ``psynet destroy ssh`` and
rerun, or choose another app name.

After a run, the app stays on the server for later runs, and PsyNet prints
the command that destroys it:

.. code-block:: bash

    psynet destroy ssh --server my-server --app my-experiment-perf

As a second check, ``performance-test ssh`` and ``performance-test local``
refuse to start if the database has participants that PsyNet bots didn't
create (bots from earlier tests and pre-fills don't count), if the
experiment runs in live mode, or if its recruiter can bring real
participants. Test recruiters are the development and mock recruiters,
Hot Air, generic, bots and simulated participants. If the experiment isn't
collecting real data, add ``--force``. You need it, for example, after your
own walkthrough of the experiment, after a Selenium walkthrough, after
loading a bot export, or for an experiment configured with Prolific. When
the run ends, PsyNet copies the bot log out of the container and prints
where it saved it.

.. _performance_testing_server_reset:

Resetting the database on a server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``performance-test ssh`` takes the same ``--reset-database``,
``--prefill-participants`` and ``--from-snapshot`` options as
``performance-test local`` (see :ref:`performance_testing_reset`):

.. code-block:: bash

    psynet performance-test ssh --app my-experiment-perf --reset-database --n-bots auto
    psynet performance-test ssh --app my-experiment-perf --prefill-participants 1500 --n-bots auto

With these options, before each later test, PsyNet stops the app's
running or restarting containers except
PostgreSQL, Redis and the front door (``frontdoor``, ``controller`` and
``cloudflared``): the web, worker, clock and PgBouncer containers, and any
services you added to the app's compose file, so that no connection holds
on to the old database. It then recreates the database from the snapshot,
as above, with ``psql`` inside the app's PostgreSQL container, empties the
app's async job queues, and starts again only the containers it stopped,
waiting until the web server answers and the workers are back. A worker
container occasionally hangs while it starts and never registers with
RQ; PsyNet restarts any worker container that hasn't registered after
60 s, once. If one still hasn't registered after 180 s, the reset fails,
and the error names the container and gives the ``docker compose restart``
command to run on the server. Pre-fill
bots run inside the web container. If a reset fails or you interrupt the
run, PsyNet starts the containers it stopped. If it can't, the command
fails, saying that the app may be stopped, and prints the ``docker compose
start`` command to run on the server. A reset interrupted between dropping
and recreating the database leaves the app without its database; destroy
the app then, and the next run deploys it again. To start a run from an
empty database rather than one left by earlier runs, destroy the app with
``psynet destroy ssh``; the next ``psynet performance-test ssh`` deploys it
again.

Before the first reset and again before every later one, the web container
checks that the app is a performance-test app, and runs the guards against
real data, with the same ``--force`` as above. Neither command
resets an experiment running in live mode, even with ``--force``. A
reset only touches the app's own database, whose name is the app name; it
refuses if the web container uses a database with another name. The free
disk space check runs inside the PostgreSQL container, and if it can't
check, it refuses to reset rather than warning.

Snapshots live in the PostgreSQL server that the app uses, and their names
include the app name, such as
``psynet_prefill_my-experiment-perf_0123456789ab_n1500``, so that apps sharing
one PostgreSQL server don't share snapshots. PostgreSQL limits database
names to 63 characters, so very long app names can't keep pre-fill
snapshots. List and drop an app's snapshots with:

.. code-block:: bash

    psynet performance-test snapshots --app my-experiment-perf
    psynet performance-test snapshots --app my-experiment-perf --drop-all

Here ``--drop-all`` drops only that app's snapshots. ``psynet destroy ssh``
drops them too: with Cloudflare ingress the app has its own PostgreSQL
container, whose volume goes with the app, and with classic ingress PsyNet
drops the app's pre-fill snapshots from the shared PostgreSQL server before
destroying the app. A run drops its temporary snapshot, named
``<app>_snapshot_<time>``, when it ends, and prints a ``dropdb`` command if
that fails. If a run is killed first, the temporary snapshot stays: with
classic ingress, drop it from the shared PostgreSQL container with
``docker exec dallinger-postgresql-1 dropdb -U dallinger <name>``, because
destroying the app doesn't.

.. _performance_testing_bot_processes:

Processes running the bots
--------------------------

The bots run as threads inside the ``performance-test`` process, which
creates their participants, sends their requests and parses the pages they
get back. Because they share a process, they also share module-level state
and the experiment instance, as in :ref:`parallel tests
<parallel_bot_tests>`. The threads take turns on one Python interpreter, so
one process can only send a few hundred requests per second: on a 16-core
server, 600 bots at ``--time-factor 1`` made 166 requests per second and kept
the process about 80% busy. Beyond that every bot slows down, and the server
gets less load than that many participants would give it, so it looks
faster than it is.

Larger tests therefore spread the bots over several processes, set with
``--bot-processes``. The ``performance-test`` process starts them once per
run and keeps all the bookkeeping, so the results look the same however many
processes there are; each process writes to the same bot log. If one stops
unexpectedly, for example because the computer ran out of memory, the test
ends early and counts as could not be tested. So does a test after which a
process does not report back, because how late its bots ran is unknown.

To check that the bots kept pace, each process running bots measures how
late its threads run: a background thread repeatedly sleeps for 50 ms and
records how much longer than that it actually took to wake up. Bot threads
wait just as long for the interpreter and the CPU before each step. The
report shows the 95th percentile of this lag for the worst process under
*Bot runtimes* as *Bot lag*. A test in which it exceeded 50 ms counts as
could not be tested, like a test whose bots could not start fast enough.
With ``--n-bots auto``, the search treats that bot count as failed, and the
summary gives the largest passing test, says the limit wasn't found and
suggests more ``--bot-processes``. Increase ``--bot-processes`` and run again
to measure further.

The report also shows the busiest process's CPU use, as a share of one core,
under *Bot process CPU*. It doesn't decide whether a test passes, but a
process near a whole core is close to its limit. Both numbers are saved in
the JSON results as ``tester_lag_p95_s`` and ``tester_cpu_share``.

With ``performance-test ssh`` the bot processes run on the experiment server
and take CPU from it, which is why ``auto`` uses at most one process per four
cores. Each test there is its own ``performance-test`` process, which
starts its bot processes again, adding a few seconds per test. Each bot
holds its own PostgreSQL connection whichever process it runs in, and each
extra process adds at most one more.

Saving results
--------------

``--json-output results.json`` writes the full results and details of the run
to a file. To record the results in the experiment's
audit, use ``psynet audit performance-test`` instead. It runs locally, takes
the same load options and ``--existing``, and writes
``audit/artifacts/performance.json`` for the audit's *Performance test*
section. That section marks each tested bot count as within limits or not,
using the same limits as the capacity search, and reminds readers that
participant numbers for a study must come from ``psynet performance-test
ssh`` on the deployment server, with ``--n-bots auto`` to find the largest
number it handles.

A typical sequence is a local sweep to see how response times grow with
load, then more worker processes or faster queries where needed, then a
capacity search (``--n-bots auto``) on the real server to choose how many
participants to run at once.
