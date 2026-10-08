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
active for one minute, prints a report, and shuts the server down. For a heavier load,
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
default ``psynet debug local`` server does not stop itself.

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

If response times are high, profile the database queries with ``psynet test
local --sql-profile``; see :doc:`/test/sqlalchemy_profiling`.

.. _performance_testing_server:

Testing on a server
-------------------

A local test is limited by your own computer. To test a real server, launch
the experiment there in debug mode, then run the test over SSH:

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
section.

A typical sequence is a local sweep to see how response times grow with
load, then more worker processes or faster queries where needed, then a
final test on the real server at the expected peak number of participants.

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

Choose the cap with a performance test on the real server: take the number
of bots at which response times start to grow, and leave some headroom.

Because the cap is an experiment variable, it can change while the study
runs, for example from a code block
(``experiment.var.max_concurrent_participants = 80``). To measure load
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
each web process skips it for 2 seconds, so a raised cap can take that long to
let people in. Use it only for load: newcomers are
told that many people are taking part and retried automatically, which would
mislead them if the study were closed for another reason.

The cap and the method only work with the ``generic`` and ``hotair``
recruiters.
Prolific and CINT participants have accepted a place, so they should not
be kept waiting. With Prolific, ``initial_recruitment_size`` already roughly
limits how many people take part at once, because PsyNet opens a new place
only when someone finishes.
