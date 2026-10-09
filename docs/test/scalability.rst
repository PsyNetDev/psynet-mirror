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
active for one minute, prints a report, and shuts the server down. It prints
the paths of the server and bot logs, which go to a
``psynet-performance-logs-<user>`` folder in the temporary directory; it keeps
the 20 most recent of each. For a heavier load,
ask for more bots and a longer run:

.. code-block:: bash

    psynet performance-test local --n-bots 25 --duration-minutes 5

To compare several levels of load, pass a comma-separated list. PsyNet runs
one test per value and prints a summary comparing them:

.. code-block:: bash

    psynet performance-test local --n-bots "5,10,20,40"

To use a server that is already running (for example from ``psynet debug
local``), add ``--existing``. A ``psynet debug local --legacy`` server stops
itself once the experiment reports that it is complete, which can happen
between bots when recruitment has closed. Start it with
``PSYNET_PERFORMANCE_TEST=1 psynet debug local --legacy`` to keep it running;
``psynet performance-test local`` does this for the server it starts. The
default ``psynet debug local`` server does not stop itself. Without
``--existing``, ``psynet performance-test local`` refuses to start while
another server uses its port or its database, because starting its own server
would stop that one and reset its database.

Local results show how the experiment copes on your computer, and the command
says so when it finishes. For a participant cap, measure the deployment server
with ``psynet performance-test ssh`` (see below).

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
- **Request metrics**: total requests, errors and throughput.
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

The bots fetch pages and submit answers without a browser, so the results
leave out the static files, media and JavaScript requests that participants'
browsers make.

If response times are high, profile the database queries with ``psynet test
local --sql-profile``; see :doc:`/test/sqlalchemy_profiling`.

.. _performance_testing_capacity:

Finding the server's capacity
-----------------------------

``--n-bots auto`` searches for the largest number of bots the server handles
well, so you don't have to guess a list of counts:

.. code-block:: bash

    psynet performance-test local --n-bots auto --time-factor 1 --duration-minutes 3

A test counts as within capacity if no request or bot errors occur and both
of these stay within their limits:

- the 95th-percentile response time for ``/timeline`` and ``/response``,
  limited by ``--max-p95-ms`` (default 500);
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
they are within 10% of each other, so it usually runs six to ten tests. It
stops at 2,000 bots.

The summary at the end of every run reports the capacity it found and, once a
larger bot count has exceeded the limits, suggests a cap of 80% of it, for
example::

    Capacity: about 160 concurrent bots kept p95 response time under 500 ms, p95 async queue wait under 5 s and no errors; 170 did not (p95 response time 622 ms).
    Suggested max_concurrent_participants: 128 (80% of 160)

Run the search on the server you will deploy to, with ``--time-factor 1`` so
that bots work at a realistic pace; bots with ``--time-factor 0`` load the
server far more than people do. Each test's measurement window includes the
time bots take to start (about 10 per second by default), so use a
``--duration-minutes`` of at least two or three for steady results. A test
whose bots didn't all start within the window counts as exceeding the limits,
and the summary warns when starting the bots took more than a quarter of the
test.

.. _performance_testing_server:

Testing on a server
-------------------

A local test is limited by your own computer, because the bots share its CPUs
with the server. The bots run as threads inside the ``performance-test``
process, so they are cheap: on a four-core computer, 200 bots working at a
realistic pace used about a third of one core, against nearly three cores for
the server. Because the bots share a process, they also share module-level
state and the experiment instance, as in :ref:`parallel tests
<parallel_bot_tests>`. To test a real server, launch the experiment there in
debug mode, then run the test over SSH. The bots then run inside the server's
web container, so they still take a little of its CPU:

.. code-block:: bash

    psynet debug ssh --app my-experiment
    psynet performance-test ssh --app my-experiment --n-bots 50 --duration-minutes 10

The test does not reset the database, so repeated runs accumulate data. Make
sure the app allows enough participants for the number of bots, and that
nobody else is using it during the test.

Saving results
--------------

``--json-output results.json`` writes the full results and details of the run
to a file (local tests only). To record the results in the experiment's
audit, use ``psynet audit performance-test`` instead. It runs locally, takes
the same load options and ``--existing``, and writes
``audit/artifacts/performance.json`` for the audit's *Performance test*
section. That section marks each tested bot count as within limits or not,
using the same response-time and queue-wait limits as the capacity search,
and reminds readers that participant numbers for a study must come from
``psynet performance-test ssh`` on the deployment server, with
``--n-bots auto`` to find the largest number it handles.

A typical sequence is a local sweep to see how response times grow with
load, then more worker processes or faster queries where needed, then a
capacity search (``--n-bots auto``) on the real server to choose the
participant cap.
