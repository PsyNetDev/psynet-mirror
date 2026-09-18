.. _performance_testing:

==============================
Testing experiment performance
==============================

Before you deploy an experiment to real participants, it's worth checking how
well your server copes under load. A timeline that feels snappy with a single
bot can behave very differently when dozens of participants hit the server at
once: HTTP responses slow down, asynchronous processes pile up in the queue, and
wait pages start to drag.

To catch such situations in advance, you should use PsyNet's
``performance-test`` command. It launches a stream of bots against a running
experiment, attempts to maintain a target number of active bots, and then
reports detailed latency and throughput statistics. This helps you judge whether
your configuration is ready for your expected peak number of simultaneous
participants.

This functionality should not be confused with ``psynet test``, which is used
for verifying the correctness of an experiment with a small number of
participants (see :ref:`testing experiment logic <tests>`). In practice you'll
want to get an experiment passing ``psynet test`` first, then use
``performance-test`` to check that it scales.

Quick start
-----------

From your experiment directory, run:

.. code-block:: bash

    psynet performance-test local

By default this starts a fresh local experiment server for you, attempts to keep
``Experiment.test_n_bots`` bots active for one minute, prints a report, and then
shuts the server down again. You don't need to launch a server beforehand.

To simulate a heavier load, ask for more bots and a longer run:

.. code-block:: bash

    psynet performance-test local --n-bots 25 --duration-minutes 5

Controlling the load
--------------------

The behavior of the test is governed by a handful of options:

``--n-bots``
    The target number of backend bots to keep running concurrently. PsyNet
    launches the remaining bots after the first bot initializes, then replaces
    bots as they finish. The load therefore ramps up towards the target before
    staying roughly constant. Defaults to ``Experiment.test_n_bots``.

``--duration-minutes``
    The total measurement window in minutes. Timing begins before the first bot
    initializes, so this includes initialization and ramp-up rather than
    guaranteeing the full duration at target concurrency. Choose a run long
    enough for the target number of bots to become active. Defaults to
    ``Experiment.test_duration_minutes`` (``1`` minute).

``--stagger``
    The average delay, in seconds, between starting successive bots. Real
    participants don't all arrive at once, so bots are started with random gaps
    drawn from a gamma distribution centred on this value (bounded at five times
    the value). Defaults to ``Experiment.test_parallel_stagger_interval_s``
    (``0.1`` s).

``--time-factor``
    A multiplier applied to the time estimates in your timeline, controlling how
    quickly each bot works through the experiment. The actual multiplier varies
    randomly around this value (a lognormal distribution bounded at three times
    the value), so bots don't move in lockstep. A value of ``0`` makes bots race
    through as fast as possible; the default of ``1.0`` roughly mimics real
    participant pacing.

These bots exercise participant-facing HTTP requests and server-side processing;
they don't render the experiment in a browser. Use browser-based testing
separately when you need to measure frontend behavior.

For example, to model up to 50 simultaneously active participants who trickle in
over time and work through the experiment at a realistic pace:

.. code-block:: bash

    psynet performance-test local --n-bots 50 --stagger 2 --time-factor 1 --duration-minutes 10

Sweeping several concurrency levels
-----------------------------------

To see how the server scales, pass a comma-separated list to ``--n-bots``. PsyNet
runs one test per value in sequence and then prints a cumulative summary
comparing them. Use a duration long enough for every test to reach its target:

.. code-block:: bash

    psynet performance-test local --n-bots "5,10,20,40"

The summary table shows, for each bot count, the number of bots that succeeded,
total requests, throughput (requests per second), the median response time, and
the median async-process queue delay. When multiple counts are run, it also shows
each metric relative to the first (lowest) row, so you can spot the point where
response times or queue delays start climbing faster than the load.

Reading the results
-------------------

Each individual test prints several sections. The most useful ones are:

* **Bot outcomes** — how many bots were started, completed successfully,
  completed with an error, or were still running when time ran out, plus an
  overall completion rate.
* **Bot runtimes** — how long bots took, broken down by outcome (succeeded,
  failed, timed out), along with bot initialization times.
* **Request metrics** — total requests, request errors, and throughput in
  requests per second.
* **Response times** — median, 95th/99th percentile, max, mean, and standard
  deviation of HTTP response times for the key participant-facing endpoints
  (``/timeline`` and ``/response``). The percentiles are usually more
  informative than the mean, since a few slow requests can badly affect the
  participant experience.
* **Wait page times** — how long successful bots spent on wait pages (relevant
  for synchronized experiments).
* **Trials per bot** — the min/median/max number of trials completed by
  successful bots.
* **Async process times** — for experiments that run asynchronous processes
  (e.g. audio analysis, media generation), this reports both execution time and
  **queue delay** (time spent waiting in the RQ queue) per process type. A high
  "Q Share" — the proportion of total time spent queuing rather than executing —
  is highlighted in yellow or red, and is a strong signal that you need more
  worker processes.

Testing against a remote server
-------------------------------

Local tests are limited by your own machine, which is rarely representative of a
production server. To test against a real server over SSH, first launch the
experiment there in debug mode:

.. code-block:: bash

    psynet debug ssh --app my-experiment

Then run the performance test against it:

.. code-block:: bash

    psynet performance-test ssh --app my-experiment --n-bots 50 --duration-minutes 10

A few things to keep in mind for SSH tests:

* The test uses whatever state already exists on the server; it does **not**
  reset the database. If you run it repeatedly, results accumulate.
* Make sure the app is configured to allow enough participants for the number of
  bots you want to run.
* If the app is being used by anyone else during the test, the results will not
  be reliable.
* ``--json-output`` / ``--audit`` (see below) are not currently supported
  over SSH; use ``performance-test local`` with those options for
  machine-readable results.

Reusing an already-running local server
---------------------------------------

If you already have a local server running (for example via ``psynet debug
local``), you can point the test at it instead of starting a new one with
``--existing``:

.. code-block:: bash

    psynet performance-test local --existing --n-bots 25

This is handy when you want to run several tests back-to-back without paying the
server startup cost each time.

Saving results as JSON
----------------------

Add ``--json-output`` to write the full results, along with metadata about the
run (PsyNet/Dallinger/Python versions, platform, timestamps, and the options
used), to a JSON file:

.. code-block:: bash

    psynet performance-test local --n-bots "10,25,50" --json-output results.json

When the experiment is being packaged as a PsyNet audit, prefer ``--audit``
instead. It writes the canonical audit path
``<audit>/artifacts/performance.json`` (creating ``artifacts/`` if needed) and
marks ``performance_result`` present. Use ``--no-mark-present`` to write the
file without updating ``audit.json``:

.. code-block:: bash

    # From the experiment root
    psynet performance-test local --n-bots 40 --duration-minutes 5 --audit

Do not combine ``--json-output`` and ``--audit``.

This is useful for tracking performance over time or feeding results into other
tools. PsyNet's own :ref:`ASV benchmark suite <asv_performance_tests>` uses
exactly this mechanism to record end-to-end experiment performance across
commits.

Using performance tests in practice
-----------------------------------

A typical workflow looks like this:

1. Get the experiment passing ``psynet test`` so you know the logic is correct.
2. Run a local sweep (e.g. ``--n-bots "5,10,20,40"``) to get a first sense of how
   response times and queue delays grow with load.
3. If async-process queue delays dominate, increase the number of worker
   processes and re-test; if HTTP response times dominate, you may need a larger
   web server or to optimize slow request handlers (the
   :ref:`SQLAlchemy profiler <sqlalchemy_profiling>` can help pinpoint slow
   database queries).
4. Once the local picture looks reasonable, repeat the test against a real
   server over SSH at a concurrency level matching your expected peak number of
   simultaneous participants, to confirm the deployment can handle it.

By finding the point where performance degrades *before* you recruit real
participants, you can size your server appropriately and avoid a bad experience
(or lost data) during a live experiment.

.. seealso::

    * :ref:`Testing experiment logic <tests>` — correctness testing with bots.
    * :ref:`SQLAlchemy profiling <sqlalchemy_profiling>` — pinpointing slow
      database queries.
    * :ref:`ASV performance tests <asv_performance_tests>` — how PsyNet tracks
      its own performance over time.
