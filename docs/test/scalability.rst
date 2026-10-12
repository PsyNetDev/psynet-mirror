.. _performance_testing:

===================
Testing scalability
===================

``psynet performance-test`` keeps a target number of bots active on a running
experiment and reports response times, throughput and queue delays.

Run it once :doc:`back-end tests <backend>` pass.

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

Local results show how the experiment copes on your computer. For a
participant cap, measure the deployment server with
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
    is at most 30 minutes, so that a capacity search of a long study stays
    practical, and at least ``Experiment.test_duration_minutes`` (one
    minute). A test shorter than one session sees only the start of the
    study, when all the bots arrive at once, and the suite warns about it.
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
    at once. With ``--n-bots auto`` every test uses the same window, so
    larger counts arrive faster. Bots that replace finished ones still start
    after ``Experiment.test_parallel_stagger_interval_s``, so
    ``--arrival-minutes`` can't be combined with ``--stagger``. The window
    must be shorter than ``--duration-minutes``; without
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
  is not yet counted as failed.
- **Bot runtimes**, separately for each of these outcomes, and **trials per
  bot** (for bots that completed successfully).
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
- **Async process times**: for experiments with asynchronous processes, such
  as audio analysis, both the execution time and the time spent waiting in
  the queue. A high queue share, highlighted in yellow or red, means more
  worker processes are needed.
- **Start-up vs steady state**: the request count, 95th-percentile response
  time, request errors and 95th-percentile async queue wait, separately for
  the start-up and the steady state. The start-up lasts until the first bot
  completes the experiment: until then every bot is in its first session,
  as when a study opens and its first participants arrive together, so
  queues fill up and slow pages are hit by everyone at once. The steady
  state is the rest of the test, when bots finish and are replaced at
  different points of the experiment. The table appears when the steady
  state lasts at least a minute; otherwise the report says how far the
  test got.
- **Database rows**: the rows in the tables that grow as a study collects
  data (participants, trials, responses, nodes, networks, async processes
  and assets), before the test and after it. See
  :ref:`performance_testing_database_size`.

Response times are measured inside the server, from when a web worker starts
handling a request until it finishes. They do not include time that a request
spends waiting for a free worker. When the server's CPUs are fully used, that
waiting grows faster than the reported times, so also watch the server's CPU
use and the number of request errors.

The bots fetch pages and submit answers without a browser. They also run
the server-side work that answers trigger, such as async processes, and
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

A test counts as within capacity if these stay within their limits:

- the share of ``/timeline`` and ``/response`` requests that fail, at most
  0.1% (one failed request is always allowed), and the share of bots that
  fail, at most 1%. A single stray error doesn't fail a test, however short,
  but the summary still reports any errors at the capacity it found. Busy
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
- the 95th-percentile time that async processes wait in the queue for a
  worker, limited by ``--max-queue-p95-s`` (default 5). Participants often
  sit on a wait page during this time, so it matters as much as response
  time. Processes still waiting when the test ends count with the time they
  have waited so far, so a queue that never drains fails the test;
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
  failing count exceeded the summary reports the capacity as a lower bound,
  without a participant cap. Other failures, such as prescreens, are part
  of the design: the summary reports them but they don't count against
  capacity.

The limits apply to the whole test, start-up included, because a real study
also has a start-up burst: recruiters often release many places at once when
a study opens. When the smallest failing count exceeded the response-time,
request-error or queue limits only in its start-up, the summary says so. If
your participants will arrive gradually, test that with ``--arrival-minutes``
rather than relying on the steady state alone.

The search's tests are short and their bots arrive together, so for most
studies they see only the start-up. In an experiment with async processes,
such as audio analysis, or with long timeline holds, every bot reaches each
process and each hold at the same moment, so queue waits are longer than
when participants arrive spread out, and the search underestimates the
capacity. The search therefore ends with a *confirmation test*: it runs the
participant cap it suggests (80% of the capacity), with bots arriving
evenly over one participant session and the test lasting two sessions, at
most an hour, so that the test reaches its steady state. A study over 30
minutes gets less than two sessions, and one over about an hour no steady
state, so for long studies also run a long test of the cap by hand. With your own
``--arrival-minutes``, the confirmation keeps that window and lasts a
session longer. If the confirmation test stays within the limits, the
summary reports the cap as confirmed. If not, it reports the cap as not
confirmed, shows which limits the start-up and the steady state exceeded,
and suggests a lower cap, scaled by how far the test overshot its limits
(but at least half the tested cap), with the command to check it. It does
not search again. Add ``--no-confirm`` to skip the confirmation test; it is
always skipped with ``--time-factor 0``, whose pace isn't realistic, and
when the search suggests no cap.

The summary names the limit that a failing test exceeded. If the queue limit
is what caps capacity, add worker processes with the ``num_dynos_worker``
config variable (see :doc:`/reference/configuration`) before resorting to a
lower participant cap.

How many async processes a worker process can handle depends on what they
do. Each worker process runs up to 20 jobs at once with gevent, but jobs
only overlap while they wait, for example on a web API, the database or
``time.sleep``. A job that keeps the CPU busy, such as audio analysis in
Python, blocks the other jobs in its process until it finishes. In the
``async_codeblock`` demo, one worker process finished about 14 one-second
jobs per second when they slept, but only about one per second when they
computed. For CPU-bound jobs, plan on about one worker process per CPU core
and on throughput of one job at a time per process. The async section of
the report shows the number of worker processes and how many jobs they can
run at once.

The search starts at 10 bots and doubles the count until a test fails, then
halves the gap between the largest passing and smallest failing counts until
they are within 10% of each other. It stops at 2,000 bots. For a server that
handles more than about 100 bots this takes 8 to 12 tests. By default each
search test lasts one participant session, rounded up to whole minutes, at
most 5 minutes and at least ``Experiment.test_duration_minutes``;
``--duration-minutes`` sets another length. A search of a 12-minute study
therefore takes 40 to 60 minutes, and its confirmation test another 24
minutes. The run prints its upper bound when it starts.

When bots fail, the report lists what went wrong, for example
``HTTP 500 on /response``. The request error count only includes errors that
the server managed to log, so a server that cannot reach its database shows
them under *Bot errors* instead.

The summary at the end of every run reports the capacity it found and, once a
larger bot count has exceeded the limits, suggests capping the number of
participants taking part at once at 80% of it. After a confirmation test the
cap comes from that test, for example::

    Capacity: about 160 concurrent bots kept p95 response time under 500 ms, p95 async queue wait under 5 s and at most 0.1% of requests failing (1 always allowed), 1% of requests answered busy or stale (10 always allowed), 1% of bots failing and 1% of participants failed by the experiment for waiting too long; 170 did not (p95 response time 622 ms).
    Confirmed: the 128-bot confirmation test (bots arriving over 12 min, 24 min long) kept the same limits. Cap concurrent participants at about 128.

Without a confirmation test, the second line reads ``Cap concurrent
participants at about 128 (80% of 160).``

For rough capacities of common server sizes, based on one test on a real
server, see :ref:`choosing_server_size`.

Run the search on the server you will deploy to, with ``--time-factor 1`` so
that bots work at a realistic pace; bots with ``--time-factor 0`` load the
server far more than people do. Each test's measurement window includes the
time bots take to start, so for steady results of a single bot count keep
the default ``--duration-minutes``, or at least one participant session. A test whose bots didn't all start within the
window counts as exceeding the limits, and the summary warns when starting
the bots took more than a quarter of the test.

With ``--json-output``, each result records the test's
``duration_minutes``, ``arrival_minutes`` and ``session_minutes`` (the
estimated session times ``--time-factor``), its ``startup_phase`` and
``steady_state_phase`` metrics (including the number of async processes in
each), and per async process label, in ``process_stats``, how long the
processes took and waited. The confirmation test has ``confirmation`` set,
and the options record ``confirmation_skipped`` with the reason it didn't
run. When the search tests and a long test with spread-out arrivals
disagree, trust the long test. For async processes that keep the CPU busy,
you can also check worker throughput by hand: one worker process keeps up
with about as many participants at once as a session lasts divided by the
processing time each participant needs (the average times in
``process_stats`` times the number of each process per participant). For
example, 43 s of audio analysis per 12-minute session lets one worker
process keep up with about 16 participants.

The processes running the bots create each bot's participant themselves, so
they can only start new bots at a limited rate, which depends on the
experiment, the computer and ``--bot-processes``. The most bots they can
keep taking part at once
is roughly that start rate multiplied by how long each bot takes to finish
the experiment. A longer experiment, or a larger ``--time-factor``, keeps
more bots taking part at once. A test in which fewer than 90% of the
requested bots were ever taking part at the same time counts as exceeding
the limits. Bots that fail because PostgreSQL ran out of connections count
against the bot error limit too, but they also point to the test: the bots
open database connections in the processes running them that participants'
browsers don't. Bots that run late because their process is too busy (see
:ref:`performance_testing_bot_processes`) are a limit of the test too. These are limits of the test, not of the server, so when they are
the only limits the smallest failing
count exceeded, the summary reports the capacity as "at least" the largest
passing count and doesn't suggest a participant cap. If no count passed, it
reports that the smallest count could not be tested, with advice on what
held the test back. Response times, queue
waits, request errors and busy responses still cap the capacity in a test
that also had these limits.

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
files per waiting participant, also caps it at about 500 per worker. This
needs a Dallinger release newer than 12.4; with 12.4 and earlier, a web
worker runs out of Redis connections once about 100 participants have waited
on it.

.. _performance_testing_database_size:

Database size
-------------

Capacity depends on how much data the experiment has already collected,
not only on how many participants take part at once. Some queries read
more rows as the tables grow: in one static rating study, the same 208
bots got a 95th-percentile response time of 0.2 s while the database held
100,000 to 150,000 trials and 7 s once it held 190,000 to 214,000. A test
on a fresh database therefore measures the start of a study, and a
capacity found early in a study may not hold later.

Each test reports the rows in the tables that grow, before and after it,
under *Database rows*, and the summary shows how they changed from the
first test to the last. By default the tests don't reset the database, so
every test adds the data its bots create, and a capacity search, whose bot
counts don't run in increasing order, compares counts at different sizes.
The capacity summary warns when the database grew by more than half during
the tests (and by at least 10,000 rows), or when the largest passing and
smallest failing bot counts started with very different amounts of data,
and then suggests ``--reset-database``.

To read the numbers:

- Treat a capacity as holding for about the amount of data the tests ran
  with. Compare the trial and participant rows with what the study will
  collect: the number of participants you plan to recruit, times the
  trials each one makes.
- If the study will collect much more, test with that much data (see
  :ref:`performance_testing_reset`), or run a confirmation test that ends
  near the planned total, for example a long test at the suggested cap. If
  response times rise steadily during that test, a query is getting slower
  as data accumulates; profile it with ``psynet test local --sql-profile``
  (see :doc:`/test/sqlalchemy_profiling`).
- If the database already holds data from earlier runs, its size can make
  a small study look worse than it will be. Relaunch the experiment to
  start again from an empty database.

.. _performance_testing_reset:

Starting every test from the same data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``psynet performance-test local --reset-database`` starts every test from
the same database, so that the tests of a capacity search differ only in
load:

.. code-block:: bash

    psynet performance-test local --reset-database --n-bots auto

Before the first test, PsyNet copies the experiment's database into a
snapshot database. Before each later test, it stops the experiment server,
drops the experiment's database and creates it again from the snapshot,
empties the async job queues and starts the server again. That takes a few
seconds, plus a few seconds per gigabyte of data, because PostgreSQL copies
the database's files. At the end it drops the snapshot. It only resets a
database on your own computer, and a test run only ever drops the
experiment's own database and its temporary snapshot. Kept pre-fill
snapshots (see below) are only dropped by ``psynet performance-test
snapshots``, whose ``--drop-all`` drops every pre-fill snapshot on this
computer. Files that the bots uploaded or
generated stay in the asset storage after a reset, because only the
database rows that refer to them are reset; they cost disk space but
nothing else.

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
pauses, waits for their async processes to finish, and then takes the
snapshot, so every test starts with 1,500 participants' data. The bots use
the same routes as participants, so the data is what the experiment itself
stores, but it takes time: at about 250 requests per participant, a few
hundred requests per second fill 1,500 participants in about an hour.

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
pilot with ``psynet export``, launch the experiment from the export with
``psynet debug ssh --app my-experiment --archive export.zip`` (see
:ref:`deploy_from_archive`), and run ``psynet performance-test ssh``
against it. Every test then starts with at least the pilot's data.

These options need the server that ``performance-test local`` starts, so
they can't be combined with ``--existing``; ``performance-test ssh`` does
not support them yet.

.. _performance_testing_server:

Testing on a server
-------------------

A local test is limited by your own computer, because the bots share its CPUs
with the server. The bots are cheap (see
:ref:`performance_testing_bot_processes`): on a four-core computer, 200 bots
working at a realistic pace used about a third of one core, against nearly
three cores for the server. To test a real server, launch the experiment there in
debug mode, then run the test over SSH. The bots then run inside the server's
web container and send their requests straight to the experiment server,
skipping the server's web proxy and any Cloudflare tunnel, so the test
measures the experiment itself. They still take a little of the server's
CPU (about half a core for 480 bots), and a capacity search loads the whole
machine, so on a shared server check with the other users first:

.. code-block:: bash

    psynet debug ssh --app my-experiment
    psynet performance-test ssh --app my-experiment --n-bots 50 --duration-minutes 10

The test does not reset the database, so repeated runs accumulate data (see
:ref:`performance_testing_database_size`; ``--reset-database`` is only
available locally so far). Make
sure the app allows enough participants for the number of bots, and that
nobody else is using it during the test.

Performance tests add bot participants to the database and load the
server, so they must never run against an experiment that is collecting
real data. ``performance-test ssh`` and ``performance-test local`` therefore
refuse to start if the database has participants that PsyNet bots didn't
create (bots from earlier tests and pre-fills don't count), if the
experiment runs in live mode, or if its recruiter can bring real
participants. Test recruiters are the development and mock recruiters,
Hot Air, generic, bots and simulated participants. If the experiment isn't
collecting real data, add ``--force``. You need it, for example, after your
own walkthrough of the experiment, after a Selenium walkthrough, after
loading a bot export, or for an experiment configured with Prolific that
you deployed with ``psynet debug ssh``. When the run ends, PsyNet copies the
bot log out of the container and prints where it saved it.

If the server is on a private network, such as a lab computer, deploy with
``--ingress cloudflare``: Let's Encrypt cannot issue certificates for a
private address, so classic ingress fails there.

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
summary reports the capacity as at least the largest count that passed and
suggests more ``--bot-processes``. Increase ``--bot-processes`` and run again
to measure further.

The report also shows the busiest process's CPU use, as a share of one core,
under *Bot process CPU*. It doesn't decide whether a test passes, but a
process near a whole core is close to its limit. Both numbers are saved in
the JSON results as ``tester_lag_p95_s`` and ``tester_cpu_share``.

With ``performance-test ssh`` the bot processes run on the experiment server
and take CPU from it, which is why ``auto`` uses at most one process per four
cores. Each bot holds its own PostgreSQL connection whichever process it runs
in, and each extra process adds at most one more.

Saving results
--------------

``--json-output results.json`` writes the full results and details of the run
to a file (local tests only). To record the results in the experiment's
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
capacity search (``--n-bots auto``) on the real server to choose the
participant cap.
