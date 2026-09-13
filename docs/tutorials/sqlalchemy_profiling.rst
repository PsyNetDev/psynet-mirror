.. _sqlalchemy_profiling:

SQLAlchemy profiling
====================

PsyNet includes a lightweight SQLAlchemy profiler designed for terminal runs and
CI-friendly output. When enabled, it aggregates results across processes and
generates a browser-friendly HTML report with expandable queries.

Quick start
-----------

Run the experiment test with profiling enabled:

.. code-block:: bash

   psynet test local --sql-profile

At the end of the run, PsyNet prints a file path to an HTML report. Open that
file in your browser to inspect the results.

When running in a TTY (and not in CI), PsyNet will automatically open the
HTML report in your default browser. To disable this behavior, add
``--sql-profile-no-open``.

What the report shows
---------------------

The HTML report contains two tables:

* **Queries** - total time, count, mean, max, and a truncated query preview.
  Click a row to expand the full SQL (and stack trace if captured).
* **Commits** - total time, count, mean, max, callsite, and commit-type counts.

By default, the query preview shows only the first 200 characters. Expanding
the row reveals the full SQL text.

Common options
--------------

To filter or tune the capture, pass options through
``--sql-profile-options``:

.. code-block:: bash

   psynet test local --sql-profile \
     --sql-profile-options "min_ms=5,top_n=50,stack=1"

Useful options include:

* ``min_ms`` - minimum per-query duration to record (ms).
* ``top_n`` - number of rows to show in reports.
* ``stack`` - set to ``1`` to capture query stack traces for callsite context.

Output formats
--------------

By default, ``--sql-profile`` generates an HTML report and prints its path. You
can customize outputs with ``--sql-profile-format``:

.. code-block:: bash

   psynet test local --sql-profile --sql-profile-format "html,text"

Supported values are ``html`` (default), ``text``, ``json``, ``none``, or
``all``. ``none`` suppresses aggregated output entirely.

Keeping raw per-process data
----------------------------

If you want to keep the per-process JSON files, provide ``--sql-profile-dir``:

.. code-block:: bash

   psynet test local --sql-profile --sql-profile-dir /tmp/sql-profile

When no directory is provided, PsyNet uses a temporary directory. The directory
is cleaned up only when no persistent output is requested (for example,
text-only output); it is kept when writing HTML or JSON reports.

Developer investigation notes
-----------------------------

Framework contributors should also read the
:doc:`SQLAlchemy performance investigation notes <../developer/sqlalchemy_performance>`.
They record profiling methodology, retained optimization patterns, approaches
that were considered but rejected, and conditions for revisiting those
decisions.
