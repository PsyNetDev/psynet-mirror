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
That short default is a good first pass. Lengthen the run when the experiment
is nearing finalizing, especially if you want some bots to finish.

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
    ``Experiment.test_duration_minutes`` (``1`` minute). A short first pass is
    enough to see whether HTTP times look healthy. When the experiment is
    nearing finalizing, use a longer window. If you want bots to finish, the
    window needs to be at least on the order of the estimated experiment
    duration (with ``--time-factor 1``, that is roughly wall-clock participant
    time). Otherwise treat completion counts as uninformative: a multi-minute
    timeline will often show zero finished bots on a one-minute smoke run.

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
each metric relative to the first (lowest) row. Treat the response-time columns
as the ones that decide whether the load is acceptable; completion counts mix
server speed with page pacing and the length of the test window.

Reading the results
-------------------

The main numbers are the HTTP **response times** for ``/timeline`` and
``/response``. Use the median for typical assignment latency and the 95th
percentile for the tail a participant will actually feel. If those percentiles
are high, profile SQL with ``psynet test local --sql-profile`` (add
``--parallel`` when the problem only appears under concurrency) before changing
the scientific policy. Repeated identical statements usually mean an N+1 query;
see :ref:`SQLAlchemy profiling <sqlalchemy_profiling>`.

Each individual test also prints:

* **Bot outcomes** — how many bots were started, completed successfully,
  completed with an error, or were still running when time ran out.
  Zero successful completions is normal when the window is shorter than the
  experiment.
* **Bot runtimes** — how long bots took, broken down by outcome, along with
  initialization times.
* **Request metrics** — total requests, request errors, and throughput.
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
* ``--json-output`` is not currently supported over SSH; use
  ``performance-test local --json-output`` for machine-readable results.
  Audit evidence collection is local-only via
  ``psynet audit performance-test``.

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

When the experiment is being packaged as a PsyNet audit, use the audit-scoped
command instead. It writes the canonical audit path
``<audit>/artifacts/performance.json`` (creating ``artifacts/`` if needed) and
marks ``performance_result`` present:

.. code-block:: bash

    # From the experiment root
    psynet audit performance-test --n-bots 40 --duration-minutes 5

The top-level ``psynet performance-test local`` command remains available for
load testing and custom ``--json-output`` files; it never updates an audit.

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
