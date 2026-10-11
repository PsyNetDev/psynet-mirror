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
active for one minute, prints a report, and shuts the server down. Like
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
    The length of the test, including the time bots take to start. Defaults to
    ``Experiment.test_duration_minutes`` (one minute), which is enough to see
    whether response times look healthy. For bots to finish the experiment,
    the test must last about as long as the experiment itself; on shorter runs,
    completion counts are uninformative.

``--stagger``
    The average delay, in seconds, between starting bots, so that they arrive
    at random intervals as real participants do. Defaults to
    ``Experiment.test_parallel_stagger_interval_s`` (0.1 s).

``--time-factor``
    A multiplier on the time estimates in the timeline, controlling how fast
    bots work through the experiment. ``1`` (the default) roughly matches real
    participants; ``0`` makes bots go as fast as possible. Each bot's pace varies
    randomly around this value.

``--bot-processes``
    The number of processes to run the bots in (see
    :ref:`performance_testing_bot_processes`). ``auto``, the default, uses one
    process per 250 bots, up to one per four CPU cores, so tests of fewer than
    250 bots run in a single process. With ``--n-bots auto`` it plans for the
    largest count the search may test.

For example, to model up to 50 participants arriving over time and working at
a realistic pace:

.. code-block:: bash

    psynet performance-test local --n-bots 50 --stagger 2 --time-factor 1 --duration-minutes 10

Reading the results
-------------------

The main numbers are the response times for ``/timeline`` and ``/response``:
the median shows the typical delay, and the 95th percentile shows the delay
that the slowest participants experience. The report also shows:

- **Bot outcomes**: how many bots started, finished, failed or were still
  running.
- **Bot runtimes** and **trials per bot**.
- **Request metrics**: total requests, errors and throughput. A
  *Busy/stale responses (409/503)* line appears when ``/timeline`` or
  ``/response`` answered with HTTP 503, which PsyNet sends when the
  experiment is busy, or HTTP 409, which it sends when a page went stale.
  Bots retry those that PsyNet marks as busy or stale. These responses are
  not counted as request errors.
- **Wait page times**, for synchronized experiments.
- **Async process times**: for experiments with asynchronous processes, such
  as audio analysis, both the execution time and the time spent waiting in
  the queue. A high queue share, highlighted in yellow or red, means more
  worker processes are needed.

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
an experiment leans on these, also test it with real browsers.

If response times are high, profile the database queries with ``psynet test
local --sql-profile``; see :doc:`/test/sqlalchemy_profiling`.

.. _performance_testing_capacity:

Finding the server's capacity
-----------------------------

``--n-bots auto`` searches for the largest number of bots the server handles
well, so you don't have to guess a list of counts:

.. code-block:: bash

    psynet performance-test local --n-bots auto --time-factor 1 --duration-minutes 3

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
  have waited so far, so a queue that never drains fails the test.

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
handles more than about 100 bots this takes 8 to 12 tests, so a search with
``--duration-minutes 3`` takes 25 to 40 minutes; the run prints its upper
bound when it starts.

When bots fail, the report lists what went wrong, for example
``HTTP 500 on /response``. The request error count only includes errors that
the server managed to log, so a server that cannot reach its database shows
them under *Bot errors* instead.

The summary at the end of every run reports the capacity it found and, once a
larger bot count has exceeded the limits, suggests capping the number of
participants taking part at once at 80% of it, for example::

    Capacity: about 160 concurrent bots kept p95 response time under 500 ms, p95 async queue wait under 5 s and at most 0.1% of requests failing (1 always allowed), 1% of requests answered busy or stale (10 always allowed) and 1% of bots failing; 170 did not (p95 response time 622 ms).
    Cap concurrent participants at about 128 (80% of 160).

For rough capacities of common server sizes, based on one test on a real
server, see :ref:`choosing_server_size`.

Run the search on the server you will deploy to, with ``--time-factor 1`` so
that bots work at a realistic pace; bots with ``--time-factor 0`` load the
server far more than people do. Each test's measurement window includes the
time bots take to start, so use a ``--duration-minutes`` of at least two or
three for steady results. A test whose bots didn't all start within the
window counts as exceeding the limits, and the summary warns when starting
the bots took more than a quarter of the test.

One ``performance-test`` process creates each bot's participant itself, so
it can only start new bots at a limited rate, which depends on the
experiment and the computer. The most bots it can keep taking part at once
is roughly that start rate multiplied by how long each bot takes to finish
the experiment. A longer experiment, or a larger ``--time-factor``, keeps
more bots taking part at once. A test in which fewer than 90% of the
requested bots were ever taking part at the same time counts as exceeding
the limits. Bots that fail because PostgreSQL ran out of connections count
against the bot error limit too, but they also point to the test: the bots
open database connections in the test process that participants' browsers
don't. These are limits of the test, not of the server, so when they are
the only limits the smallest failing
count exceeded, the summary reports the capacity as "at least" the largest
passing count and doesn't suggest a participant cap. If no count passed, it
reports that the smallest count could not be tested, with advice on what
held the test back. Response times, queue
waits, request errors and busy responses still cap the capacity in a test
that also had these limits.

The processes running the bots can also hold a test back, when they run out
of CPU; see :ref:`performance_testing_bot_processes`.

Test the experiment at the length participants will take it. When bots
finish within seconds, the test mostly measures how quickly bots are
created and replaced rather than a realistic load, so avoid testing
shortened versions of an experiment. The test doesn't reset the database, so later tests in a
sweep run against more participants than earlier ones.

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

The test does not reset the database, so repeated runs accumulate data. Make
sure the app allows enough participants for the number of bots, and that
nobody else is using it during the test. When the run ends, PsyNet copies the
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
ends early and counts as could not be tested.

To check that the bots kept pace, each process running bots measures how
late its threads run: a background thread repeatedly sleeps for 50 ms and
records how much longer than that it actually took to wake up. Bot threads
wait just as long for the interpreter and the CPU before each step. The
report shows the 95th percentile of this lag for the worst process under
*Bot runtimes* as *Bot lag*. A test in which it exceeded 100 ms counts as
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
