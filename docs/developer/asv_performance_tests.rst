.. _asv_performance_tests:
.. highlight:: shell

=====================
ASV performance tests
=====================

PsyNet uses `Airspeed Velocity (ASV) <https://asv.readthedocs.io/>`_ to track
performance over time. The benchmark configuration lives in ``asv.conf.json``,
benchmark code lives in ``benchmarks/``, and CI stores generated result files on
the ``benchmark-results`` branch.

.. note::

    This page describes how PsyNet benchmarks *its own* performance across
    commits. If instead you want to load-test *your experiment* to check how it
    will cope with real participants, see the
    :ref:`testing experiment performance guide <performance_testing>`. The
    slow ASV tier below drives that same ``psynet performance-test`` command
    under the hood.

Benchmark tiers
===============

Benchmarks are split by directory:

- ``benchmarks/fast/`` contains hot-path microbenchmarks selected for the
  merge-request regression gate.
- ``benchmarks/slow/`` contains end-to-end benchmarks: experiment performance
  and debug-launch time. These are intentionally excluded from the
  merge-request gate, because wall-clock launches and load tests vary by more
  than its 1.25× threshold between runs, but they do run nightly on ``master``. The
  debug-launch benchmark records the fastest of three launches per profile to
  damp that noise. Because the ``master`` job is allowed to fail (see below),
  slow-tier results are tracked in the published history rather than gating
  merges. The slow ASV history focuses on median request latency and median
  async-process queue delay; participant failures and incomplete bots are left
  in the performance-test output instead of being tracked as ASV metrics.

Merge-request checks
====================

Merge requests run the ``asv_regression`` CI job when the diff includes PsyNet
package code, benchmark files, or the ASV/CI configuration those jobs use. The job uses
``asv continuous`` with ``--bench "^fast\\."`` to benchmark the merge-request
base and head commits back-to-back on the same GitLab runner. The job exits
non-zero when ASV detects a regression larger than ``--factor 1.25``. Docs,
changelog, and skill-only merge requests skip this job.

Export performance is not included in the ASV suite. End-to-end exports depend
on mutable database fixtures, filesystem caches, and subprocess startup, which
do not provide a stable enough signal for the merge-request gate's fixed
regression threshold. Export correctness remains covered by functional tests.

Default-branch checks and publishing
====================================

A nightly GitLab pipeline schedule on ``master`` runs the ``asv_benchmarks``
CI job. The schedule sets the variable ``NIGHTLY_BENCHMARKS`` to ``1``, and its
pipelines run only this job and ``pages``, which republishes the benchmark
site. The full suite takes about 35 minutes, which is too long to run on every
merge, so ``master`` push pipelines only offer the job as a manual action.
Other schedules run the usual pipeline jobs.

The job uses ``asv continuous`` without a ``--bench`` filter, so it runs both
the fast and slow benchmark tiers. It compares ``master`` as it was 24 hours
earlier (``ASV_BASE_AGE``) with the current ``master`` commit on the same
runner, and exits early if nothing has been merged since then. It writes the
generated result files, commits those results to the ``benchmark-results``
branch, pushes them, and then propagates the ASV exit status.
``asv continuous`` exits with status 1 on a regression. If a benchmark errors
or either commit fails to build, it exits with status 2 without comparing the
commits; the job log shows the failure, and the results for both commits are
still published.

The PsyNet project already has this schedule, "Nightly ASV benchmarks", which
runs at 02:00 Europe/London time; see *Build > Pipeline schedules* in GitLab.
Don't add a second one. Scheduled pipelines run as the schedule's owner, and
the owner needs the Maintainer role to run pipelines on the protected
``master`` branch. If the owner leaves the project or loses that role, another maintainer
should use *Take ownership* to keep it running.

A fork or new project needs its own setup:

- A pipeline schedule for ``master``, for example with the cron expression
  ``0 2 * * *``, with the variable ``NIGHTLY_BENCHMARKS`` set to ``1``.
- A project access token (*Settings > Access tokens*) with the Developer role
  and the ``write_repository`` scope, stored as the masked CI/CD variable
  ``BENCHMARK_RESULTS_TOKEN`` (*Settings > CI/CD > Variables*).

``asv_benchmarks`` uses the token to push the ``benchmark-results`` branch, and
``pages`` uses it to fetch that branch. When the token expires, the push fails
and the published benchmarks stop updating, so renew it before then.

The comparison uses ``--factor 2`` because the slow
``psynet performance-test`` medians commonly move by 1.2–1.3× on GitLab
runners without a code change. ``asv continuous`` applies one factor to
every benchmark it runs, so the default-branch job is also looser on the
fast suite; merge requests still gate the fast suite at ``--factor 1.25``.
The job is currently allowed to fail while the benchmark suite is being
tuned.

ASV command modes
=================

The helper script ``ci/asv-sync-results.sh`` supports two ASV command modes:

- ``asv run`` benchmarks selected commits and records their results. Use this
  when you only need fresh benchmark data.
- ``asv continuous BASE HEAD`` benchmarks ``BASE`` and ``HEAD`` back-to-back on
  the same runner, compares the results, and exits non-zero if ``HEAD``
  regresses. Use this when benchmark results should also act as a regression
  gate.

Local commands
==============

Run the fast tier locally:

.. code-block:: shell

    asv run --quick --show-stderr --bench '^fast\.'

Run a same-runner comparison locally:

.. code-block:: shell

    asv continuous --factor 1.25 --split --show-stderr --bench '^fast\.' BASE HEAD

Preview published benchmark results locally:

.. code-block:: shell

    bash ci/asv-local.sh

The preview command fetches the ``benchmark-results`` branch, runs
``asv publish``, and serves the generated pages at ``http://127.0.0.1:8080``.
