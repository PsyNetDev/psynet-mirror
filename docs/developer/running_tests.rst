.. highlight:: shell

=============
Running tests
=============

PsyNet contains a large number of automated tests to help protect the package
from bugs. This test suite includes running all the demos and checking that
they complete in the correct state.

Whenever you push a contribution to a branch of the PsyNet repository,
these automated tests will be automatically queued. They normally take 10-15 minutes
to complete. Keep an eye on the GitLab interface to see if any errors have occurred.
Resolve any errors before merging into ``master``.

Merge requests that change only documentation, changelog fragments, ``AGENTS.md``,
or non-experiment Cursor skills skip the Docker pytest and Playwright jobs.
The ``.docker_test_rules`` block in ``.gitlab-ci.yml`` lists the paths that
still trigger them, including the few docs pages whose content tests check.
Default-branch, tag, and non-MR branch pipelines always run the full suite.

That list is an allowlist: a path missing from it skips the tests on merge
requests that change only that path. If you add a top-level file or directory
that tests or the CI image depend on, or a test that reads a docs page, add
its path to ``.docker_test_rules``.

Merge-train pipelines skip jobs that already passed on the same files.
Merging goes through a GitLab merge train, whose pipeline tests the commit that
``master`` will become. That commit often has exactly the same files as the
merge request's last merged-results pipeline: when ``master`` hasn't moved and
nothing is ahead of it in the train. Rerunning the suite on it would only
delay the merge. The ``check_already_tested`` job runs first in each train
pipeline. It runs ``ci/already_tested.py``, which finds the newest finished
merged-results pipeline of the merge request that tested identical files. The
pytest, Playwright, ``docs`` and ``asv_regression`` jobs that passed there end
successfully at once, and their logs link to that pipeline. If anything
differs, or the check fails, every job runs as usual. ``master`` push
pipelines always run the full suite.

A job opts in by sourcing ``ci/skip-if-already-passed.sh`` at the start of its
``before_script``. Only add this to jobs whose result is set by the
repository files, and never to jobs that publish or deploy. Outside drift,
such as a new dependency release or a dead external link, can still change a
job's result between two runs on the same files; the full ``master`` push
pipeline catches that after the merge. ``asv_regression`` is the exception: it
runs only on merge requests, and its result also depends on runner noise. It
still opts in, because a train rerun would benchmark the same two commits
again and could only add a chance of a noisy failure.

Test parallelization
--------------------

The automated test suite is slow because it has to run more than 70 demo experiments
and more than 170 isolated test files, each in its own pytest process.
GitLab therefore splits these tests across several shard jobs, and each job
runs several tests at once in *slots*. Running the full test
suite locally will ordinarily take a very long time. It's better instead to
run individual tests locally and only run the full test suite on GitLab.

``run-ci-tests.sh`` calls ``psynet dev ci run-tests``, which works as follows:

- Tests are assigned to shards so that each shard's estimated duration is
  about the same. Estimates come from ``ci/test_durations.json``; tests that
  are missing from that file get the median duration for their kind.
- Within a shard, ``TEST_SLOTS`` tests run concurrently. Slot 0 uses the job's
  database and Redis server; every other slot gets its own database, its own
  Redis server and its own port (see :ref:`running_several_local_experiments`).
- Tests that use the same demo directory never run at the same time, because
  the ``in_experiment_directory`` fixture holds a lock on the directory.

.. _refresh_test_durations:

Each shard job publishes per-test logs in ``public/test-logs`` and its measured
durations in ``public/ci_durations_<python>_<shard>.json``; each Playwright
shard publishes ``public/playwright-<mode>-<shard>-junit.xml``. Stale estimates
only make shards less even, so the release process refreshes them once per
minor release. To refresh them from the latest passing ``master`` push pipeline
(the artifacts are public, so no token is needed; requires ``jq``), run this
from the PsyNet checkout:

.. code-block:: bash

    P=https://gitlab.com/api/v4/projects/PsyNetDev%2FPsyNet
    PIPELINE=$(curl -s "$P/pipelines?ref=master&source=push&status=success&per_page=1" | jq '.[0].id')
    DIR=$(mktemp -d)
    curl -s "$P/pipelines/$PIPELINE/jobs?per_page=100" \
      | jq -r '.[] | select(.name | test("^(tests_python_3_13|playwright_e2e_)")) | "\(.id) \(.name)"' \
      | while read -r id name shard; do
          i=${shard%/*}
          case $name in
            tests_*) f=ci_durations_3.13_$i.json ;;
            *) f=playwright-${name#playwright_e2e_}-$i-junit.xml ;;
          esac
          curl -sfL -o "$DIR/$f" "$P/jobs/$id/artifacts/public/$f" || echo "missing $f"
        done
    psynet dev ci update-test-durations "$DIR"/*

You can reproduce one CI shard locally, for example shard 4 of 12 with two
slots::

    psynet dev ci run-tests --node-total 12 --node-index 4 --slots 2

Identifying which test failed
-----------------------------
If you see that the automatic tests have failed,
visit the GitLab error logs to see which particular test failed.
You're looking for a test script with a name like ``test_assets.py``,
and a test function within that, for example ``test_assets_upload_correctly()``.

Each shard job prints one ``PASSED`` or ``FAILED`` line per test file, followed by
the full output of any failed test and a summary of all failures.
The output of every test is also saved in the job's ``public/test-logs`` artifact.

Debugging tests locally
-----------------------

It is often faster to debug test failures on your local computer rather than
on GitLab. The first step is to identify which test failed, following
the instructions above. Let's suppose that the test is located in
``tests/isolated/test_assets.py``.
The next step is to reproduce this failure on your local computer.
You can do this by running the following in your terminal:

.. code-block:: python

    pytest tests/isolated/test_assets.py --chrome -s


The ``--chrome`` argument is only needed for tests that invoke an automated
web browser; if you omit this argument for such a test,
then the test will be skipped. This behavior is inherited from Dallinger,
we plan to remove it in the future.

The ``-s`` argument tells pytest to log live output from the test as it runs.
This is normally a good idea for keeping track of what's going on.

Tests reset their database and Redis and stop local servers that use them, so
by default each local test session gets its own environment and leaves a
running ``psynet debug local`` alone. The session prints where it runs, for
example::

    PsyNet tests use database dallinger_test_5100, Redis at redis://127.0.0.1:6479 and port 5100, ...

It claims a free web port 100 or more above your ``base_port`` (so from 5100
by default), uses the database ``<database>_test_<port>`` next to
``DATABASE_URL`` (created when missing) and starts a private ``redis-server``
that stops when the session ends, so several test sessions can also run at
once. If ``redis-server`` isn't installed (for example when Redis runs only in
Docker), the session uses a spare database number on your Redis server
instead, which keeps its data apart but can still send live notifications to a
debug server's participants. If the environment can't be set up, the session stops
with an error rather than falling back to your database.

This applies to ``pytest`` runs from the PsyNet checkout, to experiments
whose ``pytest.ini`` loads ``-p psynet.pytest_environment`` (run ``psynet
scripts update`` in older experiments) and to ``psynet test local``.
``psynet test local --existing`` tests a server that is already running, so it
isn't isolated. CI jobs (where ``CI`` is set) always use their configured
services.

Isolation covers services, not files: tests still create and remove generated
files in the experiment directory. A test session therefore refuses to start
while ``psynet debug`` is serving the same directory; run the tests from a copy
of the experiment (such as a git worktree) instead.

Set ``PSYNET_TEST_ENVIRONMENT=shared`` to use your current database, Redis and
port, for example if your PostgreSQL user can't create databases. The session
then prints a warning, because it resets those services and stops any debug
server that uses them. ``PSYNET_TEST_ENVIRONMENT`` accepts only ``isolated``
(the default) and ``shared``; any other value is an error.

In most IDEs, you can run tests through the integrated test interface
or by right-clicking on test files/functions and selecting "Run Test" or "Debug Test".
The debugger will work with breakpoints as expected.

If you are using PyCharm, it is usually preferable to run the tests through
the PyCharm interface. First you have to configure PyCharm's run configurations.
Do this as follows:

1. Click 'Run', then 'Edit configurations';
2. Click 'Edit configuration templates';
3. Select 'Python tests';
4. Select 'pytest';
5. Add ``--chrome -s`` to 'Additional arguments';
6. Click OK.

Now you can right click on a particular test file or test function within PyCharm
and run the test by clicking 'Run pytest in ...', or alternatively
'Debug pytest in ...'. The latter mode is slower but supports breakpoints.

In rare cases, tests only fail when several tests are run in a particular sequence.
This is usually due to some kind of caching issue.
To reproduce such errors locally, note the failing job's shard number
(e.g. job 4/6 is shard 4 of 6) and run that shard with
``psynet dev ci run-tests`` as described in the previous section.
Use ``--slots 1`` to check whether the failure depends on tests running concurrently.

Playwright UI tests
-------------------

PsyNet includes Playwright tests under ``tests/playwright``. These can be run
using Playwright's UI mode during development:

.. code-block:: shell

    npm install
    npx playwright install chromium
    HEADLESS=false npx playwright test --ui

These tests launch demo experiments locally, so you still need PostgreSQL and
Redis running (same as for the pytest-driven e2e tests). They need Node 20 or
later, and ``participant_recording.spec.js`` also needs ``ffmpeg`` and
``ffprobe`` on ``PATH``.

Mode tags
^^^^^^^^^

Every Playwright test must declare one CI mode tag via Playwright's ``tag``
option:

* ``@both`` — safe under both in-place and legacy full-reload modes
* ``@inplace-only`` — requires default ``inplace_timeline_transitions``
* ``@legacy-only`` — requires ``inplace_timeline_transitions=false``

GitLab CI selects suites with ``--grep`` instead of hardcoding file paths:

* ``playwright_e2e_default`` runs ``@both|@inplace-only``
* ``playwright_e2e_legacy`` runs ``@both|@legacy-only``

Each job runs in three shards. ``psynet dev ci playwright-files`` chooses each
shard's spec files using the durations in ``ci/test_durations.json``, so a new
spec file needs no CI changes.

Both jobs also run ``node tests/playwright/check-mode-tags.js``, which fails if
any test is missing one of those tags. When adding a new lifecycle fixture,
prefer ``@inplace-only`` unless the assertions adapt to both modes (as demos
and ``managed_page_javascript`` do with ``@both``).

Example:

.. code-block:: javascript

    test("my lifecycle case", { tag: "@inplace-only" }, async ({ page, context }) => {
      // ...
    });

Hold-resume probes
^^^^^^^^^^^^^^^^^^

Hold specs use the helpers in ``tests/playwright/psynetHarness.js`` and
``tests/playwright/stackedHoldHarness.js``; experiments cannot import them.
When the contract is first paint, for example the last group member skipping
a partner wait, ``enterTimelineAfterGateway`` returns the first
``GET /timeline`` HTML (``entry.timeline.durationMs``), and
``lastArriverWorkRecord`` returns the last arriver's grouping request (the
302 or the submit POST), whose handler time ``requestHandlerMs`` reads. An
eventual prompt can arrive from the poller after a hold was already shown,
so do not assert it instead. When a partner is already on a hold,
``enterWaitingHold`` wraps the resume probe, silences the 2s safety poll, and
arms ``waitForHeldParticipantToResume`` before the last arriver consents;
``assertWaiterReleasedWithLastArriver`` then checks the release against
``enterSkippingHold``'s entry. Concurrent late arrivals must wrap and arm at
first paint, inside the same ``Promise.all`` as consent.

Legacy hold resumes reload the document, which destroys Playwright's execution
context. ``wrapTimelineHoldResumeProbe`` retries ``page.evaluate`` after that
navigation. ``waitForHeldParticipantToResume`` treats the same navigation as a
retry, including Playwright ``toHaveCount`` failures that report
``Received: undefined`` instead of ``Execution context was destroyed``. If a
stacked last-arrival hold clears while the test is arming the probe, treat the
page as a cleared hold (wake token and hold-resume POST) instead of failing on
the destroyed context.

Overlay linger after a published wake is last-wake→last-end wallclock,
including gunicorn listen-queue. Summaries log that interval. Stacked-hold
tests have no performance budgets, because CI load routinely doubles request
times; the only time limit is a 30000ms hang cap (fail-fast versus the 120s
step timeout) on requests, signups and overlays. A slow approved POST is not a missed wake; still assert
that the resume reason is not ``safety poll`` or ``hold timeout``. If a
legacy reload drops in-page wake clocks, a published wake token plus an
approved hold-resume POST still counts as a server wake.
Hold-release summaries print ``Server-Timing`` ``app`` versus browser wall
time (``queue~``) for the last arriver's request and the waiter's hold-resume
POST so a long linger can be split into handler time versus pool occupancy.
Do not subtract ``queue~`` from overlay linger.
``GET /timeline`` also prints ``lock``, ``page``, ``barriers``, and
``render``. Blocking-request checks use ``app`` when that header is present, so
worker-pool queueing is not treated as a slow handler. They cover
``GET /timeline`` and ``POST /load-participant``, not ``POST /participant``:
Dallinger ``@db.serialized`` retries concurrent signups with
``expovariate(0.5)`` sleep (mean 2s). GitLab Playwright jobs always set
``PSYNET_USE_LEGACY_DEBUG=1``, so they
run ``psynet debug --legacy`` (gunicorn). The default single-process Flask
reloader (``psynet debug local`` without ``--legacy``) is not exercised in
CI; run that locally when debugging reloader-only issues. Playwright hold
tests set the worker
count to the session count plus two spares so concurrent last-arrival work can
overlap every waiter hold-resume POST without starving a waiter Redis subscribe.
A short HTTP 503 on hold-resume is the
``NOWAIT`` busy retry when those requests hit the same participant row;
the in-request retry waits 250ms; if that is still busy, one delayed
``queued hold wake`` runs. The suite still fails a busy retry that lasts
500ms or more. An in-page probe that counts hold wakes or schedule calls must
swallow ``psynet.resumeTimelineHold`` and call
``window.__settleTimelineHoldResume`` before installing its counters. The helper
waits for ``resumeInFlight`` to clear and then yields one ``setTimeout(0)``: a
resume that settles with ``resumeRequested`` set queues a 0ms
``queued hold wake``, which would otherwise land in the probe.
A ``wait_while`` test that asserts ``timelineHoldWakeReceived``
must silence that 1s safety poll after the hold chip appears. Otherwise an
in-place hold-resume POST can stop the controller before the websocket
message dispatches the event, and a counter installed only with
``page.addInitScript`` after consent is already loaded never attaches.
Concurrent last arrivals may post a fourth hold-resume when the
poller and ``GET /timeline`` both publish, a stacked-hold reload posts
again once its websocket confirms it is listening, and a still-on-hold server notification posts
once more before ``ModularPage``; sequential last arrivals stay at two. Both Playwright
CI jobs use gunicorn; the default vs legacy job is in-place vs full reload.
Worker-pool ``queue~`` is therefore not reload-specific.

Last-arrival ``GET /timeline`` can 302 when ``page_uuid`` advances during
read-only render. First-paint assertions wait for the following 200 HTML
document. Waiter release clocks are compared with the last arriver's grouping
request (the first GET or the choice POST), not with how long that browser
took to paint after a legacy reload. ``waitForHeldParticipantToResume`` keeps
the previous ``holdEndedAtMs`` across a later ``timelineHoldStarted`` and
falls back to the context ``resumeLog``.

Faster local iteration for Playwright tests
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

During local test development, startup and teardown of ``psynet debug local`` can
dominate the runtime. You can avoid this by running the backend once and reusing
its recruitment URL across repeated Playwright runs.

1. In one terminal, start the demo backend once:

.. code-block:: shell

    cd demos/experiments/graphics
    psynet debug local

2. Copy the recruitment URL printed in the logs (it looks like
   ``http://127.0.0.1:5000/ad?...&mode=debug``).

3. In a second terminal, run Playwright with ``PSYNET_RECRUITMENT_URL``:

.. code-block:: shell

    PSYNET_RECRUITMENT_URL="http://127.0.0.1:5000/ad?recruiter=hotair&assignmentId=...&hitId=...&workerId=...&mode=debug" \
    npx playwright test tests/playwright/demos/graphics.spec.js --reporter=line

When this environment variable is set, the Playwright harness attaches to the
already running backend and skips backend spawn/teardown for each test run.
This can significantly speed up iterative debugging.

If you change Python experiment code, restart ``psynet debug local`` before the
next test run so your changes are loaded.

Playwright harness startup options
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Playwright harness launches experiments with ``psynet debug local`` by default
and does not force legacy mode. That Flask reloader is one process; use
``PSYNET_USE_LEGACY_DEBUG=1`` (or ``psynet debug local --legacy``) for gunicorn
workers. GitLab Playwright jobs set
``PSYNET_USE_LEGACY_DEBUG=1`` so those runs use gunicorn. CI therefore never
exercises the default single-process Flask debug server. ``psynet debug local
--legacy`` starts four gunicorn workers by default. Playwright stacked-hold
tests set ``PSYNET_LEGACY_DEBUG_GUNICORN_THREADS`` to the session count plus
two spares so concurrent last-arrival ``GET /timeline`` can overlap every waiter
hold-resume POST without starving a waiter Redis subscribe. The
default vs legacy *job* split is still in-place vs full reload
(``inplace_timeline_transitions``), not Flask vs gunicorn.

Optional environment variables:

- ``PSYNET_USE_LEGACY_DEBUG=1``: add ``--legacy`` to the debug command.
- ``PSYNET_LEGACY_DEBUG_GUNICORN_THREADS``: gunicorn worker processes for
  ``psynet debug local --legacy`` (default ``4``). Stacked-hold tests set this to
  the session count plus two spares.
- ``PSYNET_DEBUG_EXTRA_FLAGS="..."``: append extra flags to the debug command
  (for local troubleshooting).
- ``PSYNET_USE_UV_RUN=1``: launch via ``uv run`` instead of invoking ``psynet``
  directly (useful when ``psynet`` resolves to the wrong Python environment).
- ``PSYNET_UV_RUN_TARGET="..."``: optional override for the command target used
  with ``uv run`` (defaults to the resolved ``psynet`` command path).

Example using uv-backed startup for a single Playwright test:

.. code-block:: shell

    PSYNET_USE_UV_RUN=1 \
    npx playwright test tests/playwright/demos/graphics.spec.js --reporter=line

Finding Playwright CI artifacts in GitLab
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Playwright artifacts are uploaded by the ``playwright_e2e_default`` and
``playwright_e2e_legacy`` jobs. Each has three shards (``1/3`` to ``3/3``),
and each shard uploads the artifacts of its own spec files.

To view them in GitLab:

1. Open the pipeline.
2. Open the relevant Playwright job.
3. In the **Job artifacts** section on the right sidebar you can download or browse uploaded artifacts.

Uploaded artifacts include:

- ``playwright-report/``: Playwright HTML report (open ``playwright-report/index.html``).
- ``test-results/``: per-test failure assets (screenshots, traces, videos).
- ``public/playwright-<mode>-<shard>-junit.xml``: JUnit XML used for test report
  integration and for refreshing ``ci/test_durations.json``.


Debugging tests via Docker
--------------------------

If you are making changes to the ``Dockerfile`` in your merge request,
then these changes may not be reflected in the tests you run, because the
tests by default pull the PsyNet master Docker base image.
In order to make these tests work properly, you need to run the tests on
a Docker image built from your branch. To do this, do the following.

First, go to your PsyNet source code directory and run the following
(make sure you are not within a demo directory):

::

    docker build -t registry.gitlab.com/psynetdev/psynet:master .

This will build the PsyNet docker image from your local branch and tag it as if it were
the master branch. Don't worry, this won't be uploaded to GitLab unless you say so.

If you now want to run a demo test, then you should be able to do so as follows:

::

    psynet test local

Note that this does not quite match the Docker environment that the CI tests are using,
but it should be close enough. We might document alternative approaches later.


Occasional test failures, and running tests repeatedly
------------------------------------------------------

Sometimes we encounter test failures that only occur occasionally. Often the best way to
reproduce such failures is to run the test script repeatedly until a failure happens to occur.
This can be done with a script like the following:

::

    while psynet test local; do :; done

Sporadic test failures typically involve race conditions where two separate processes try to
operate on the same database objects simultaneously. This can cause inconsistent object states
and apparent logic errors. Processes to consider include:

- 'Web' processes (invoked when a participant submits a response and/or navigates to a new page)
- 'Clock' processes (in particular growing networks and checking barriers)
- 'Worker' processes (e.g. asynchronous processing of an audio recording)

The best way to avoid such errors is typically to add some database locking.
In SQLAlchemy this is achieved using the ``.for_update`` method, which tells
the database that certain rows should be left alone by other processes until the current
process calls ``commit()``. For example, in the ``grow_network`` method we have the following:

::

    network = (
        TrialNetwork.query.with_for_update(of=[TrialNetwork, TrialNode])
        .populate_existing()
        .get(network_id)
    )

This logic means that noone can touch the selected network or its head node until
the next ``commit()`` call.

Note that we almost always combine ``with_for_update`` with ``.populate_existing``;
the latter is important for ensuring that object attributes are updated to their latest values.
