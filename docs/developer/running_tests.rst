.. _developer:
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
Errors should be resolved before merging branches into ``dev`` or ``master``.

Test parallelization
--------------------

The automated test suite is slow because it has to run more than 70 demo experiments.
GitLab therefore runs these tests in parallel to save time. This is not
really practical on most local machines, so be warned that running the full test
suite locally will ordinarily take a very long time. It's better instead to
run individual tests locally and only run the full test suite on GitLab.

Identifying which test failed
-----------------------------
If you see that the automatic tests have failed,
visit the GitLab error logs to see which particular test failed.
You're looking for a test script with a name like ``test_assets.py``,
and a test function within that, for example ``test_assets_upload_correctly()``.

The umbrella test scripts ``test_run_all_demos.py`` and ``test_run_isolated_tests.py``
iterate through many subsidiary test scripts.
If you see a failure there, inspect the logs to see exactly which
subsidiary test script failed.

Debugging tests locally
-----------------------

It is often faster to debug test failures on your local computer rather than
on GitLab. The first step is to identify which test failed, following
the instructions above. Let's suppose that the test is located in
``tests/test_assets.py``.
The next step is to reproduce this failure on your local computer.
You can do this by running the following in your terminal:

.. code-block:: python

    pytest tests/test_assets.py --chrome -s


The ``--chrome`` argument is only needed for tests that invoke an automated
web browser; if you omit this argument for such a test,
then the test will be skipped. This behavior is inherited from Dallinger,
we plan to remove it in the future.

The ``-s`` argument tells pytest to log live output from the test as it runs.
This is normally a good idea for keeping track of what's going on.

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
To reproduce such errors locally, look at the Jobs list in GitLab and work out
(a) how many parallel test groups there are (at the time of writing there are 10)
and (b) what's the number of the test group  you want to reproduce locally
(e.g. Job 4/10 is number 4).
Install the ``pytest-test-groups`` in your local Python environment if you don't have it already
(``pip3 install pytest-test-groups``), then run a command like the following:

::

    pytest --test-group-count 10 --test-group=4 --test-group-random-seed=12345 --ignore=tests/local_only --ignore=tests/isolated --chrome tests

setting the values of ``--test-group-count`` and ``--test-group`` as appropriate.

Playwright UI tests
-------------------

PsyNet includes Playwright tests under ``tests/playwright``. These can be run
using Playwright's UI mode during development:

.. code-block:: shell

    npm install
    npx playwright install chromium
    HEADLESS=false npx playwright test --ui

These tests launch demo experiments locally, so you still need PostgreSQL and
Redis running (same as for the pytest-driven e2e tests).

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

Both jobs also run ``node tests/playwright/check-mode-tags.js``, which fails if
any test is missing one of those tags. When adding a new lifecycle fixture,
prefer ``@inplace-only`` unless the assertions adapt to both modes (as demos
and ``managed_page_javascript`` do with ``@both``).

Example:

.. code-block:: javascript

    test("my lifecycle case", { tag: "@inplace-only" }, async ({ page, context }) => {
      // ...
    });

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
and does not force legacy mode.

Optional environment variables:

- ``PSYNET_USE_LEGACY_DEBUG=1``: add ``--legacy`` to the debug command.
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
``playwright_e2e_legacy`` jobs.

To view them in GitLab:

1. Open the pipeline.
2. Open the relevant Playwright job.
3. In the **Job artifacts** section on the right sidebar you can download or browse uploaded artifacts.

Uploaded artifacts include:

- ``playwright-report/``: Playwright HTML report (open ``playwright-report/index.html``).
- ``test-results/``: per-test failure assets (screenshots, traces, videos).
- ``public/playwright-junit.xml``: JUnit XML used for test report integration.


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
