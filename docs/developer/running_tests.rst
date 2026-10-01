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

Hold-resume probes
^^^^^^^^^^^^^^^^^^

Legacy hold resumes reload the document, which destroys Playwright's execution
context. ``wrapTimelineHoldResumeProbe`` retries ``page.evaluate`` after that
navigation. ``waitForHeldParticipantToResume`` treats the same navigation as a
retry, including Playwright ``toHaveCount`` failures that report
``Received: undefined`` instead of ``Execution context was destroyed``. If a
stacked last-arrival hold clears while the test is arming the probe, treat the
page as a cleared hold (wake token and hold-resume POST) instead of failing on
the destroyed context.

Overlay linger after a published wake is last-wake→last-end wallclock,
including gunicorn listen-queue. Summaries log that interval; the hung-overlay
cap is 30000ms (fail-fast versus the 120s step timeout), not a per-hop
performance budget. A slow approved POST is not a missed wake; still assert
that the resume reason is not ``safety poll`` or ``hold timeout``. If a
legacy reload drops in-page wake clocks, a published wake token plus an
approved hold-resume POST still counts as a server wake.
Hold-release summaries print ``Server-Timing`` ``app`` versus browser wall
time (``queue~``) for the last arriver's request and the waiter's hold-resume
POST so a long linger can be split into handler time versus pool occupancy.
Do not subtract ``queue~`` from overlay linger.
``GET /timeline`` also prints ``lock``, ``page``, ``barriers``, and
``render``. Blocking-request checks use ``app`` when that header is present, so
worker-pool queueing is not treated as a slow handler. The 3000ms entry
budget applies to ``GET /timeline`` and ``POST /load-participant``, not to
``POST /participant``. Dallinger ``@db.serialized`` retries concurrent
signups with ``expovariate(0.5)`` sleep (mean 2s); overlapping
``consent→timeline`` uses a 15000ms serialized-signup budget. Sequential
starts still have the 6000ms start-page budget. GitLab Playwright jobs always set ``PSYNET_USE_LEGACY_DEBUG=1``, so they
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
500ms or more. A ``wait_while`` test that asserts ``timelineHoldWakeReceived``
must silence that 1s safety poll after the hold chip appears. Otherwise an
in-place hold-resume POST can stop the controller before the websocket
message dispatches the event, and a counter installed only with
``page.addInitScript`` after consent is already loaded never attaches.
Concurrent last arrivals may post a fourth hold-resume when the
poller and ``GET /timeline`` both publish, a stacked-hold reload posts
again on websocket onOpen, and a still-on-hold server notification posts
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
``PSYNET_USE_LEGACY_DEBUG=1`` (or ``psynet debug --legacy``) for gunicorn
workers. GitLab Playwright jobs set
``PSYNET_USE_LEGACY_DEBUG=1`` so those runs use gunicorn. CI therefore never
exercises the default single-process Flask debug server. ``psynet debug
--legacy`` starts four gunicorn workers by default. Playwright stacked-hold
tests set ``PSYNET_LEGACY_DEBUG_GUNICORN_THREADS`` to the session count plus
two spares so concurrent last-arrival ``GET /timeline`` can overlap every waiter
hold-resume POST without starving a waiter Redis subscribe. The
default vs legacy *job* split is still in-place vs full reload
(``inplace_timeline_transitions``), not Flask vs gunicorn.

Optional environment variables:

- ``PSYNET_USE_LEGACY_DEBUG=1``: add ``--legacy`` to the debug command.
- ``PSYNET_LEGACY_DEBUG_GUNICORN_THREADS``: gunicorn worker processes for
  ``psynet debug --legacy`` (default ``4``). Stacked-hold tests set this to
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


Recording upload development checks
-----------------------------------

LocalStorage answer video uses asynchronous delivery in in-place experiments.
The private fixture also forces this transport in legacy mode for loss checks. Run its
server and browser checks separately from the experiment demos; database fixtures
reset their database and must not run
alongside a demo using that same database.

.. code-block:: shell

    pytest tests/isolated/test_media_upload.py tests/isolated/test_chain_growth_queries.py tests/isolated/test_finalize_pending_trials.py
    pytest tests/isolated/test_recording_submission.py tests/isolated/test_wait_for_recording.py
    pytest tests/isolated/test_recording_reporting.py tests/isolated/test_export_transport.py
    npx playwright test media_upload_queue.spec.js
    npx playwright test asynchronous_recording.spec.js dual_recording_upload.spec.js
    inplace_timeline_transitions=false npx playwright test recording_legacy_navigation.spec.js
    npx playwright test missing_chain_recording.spec.js
    npx playwright test recording_document_loss.spec.js
    pytest tests/isolated/test_background_recording.py
    npx playwright test background_recording.spec.js
    npx playwright test background_capture.spec.js same_session_page_update.spec.js
    npx playwright test task_background_recording.spec.js
    npx playwright test demos/imitation_chain_video.spec.js demos/video_feature.spec.js

The video imitation-chain demo exercises recording-dependent playback and chain
progression. The ordinary video demo also covers camera-plus-screen recording.
Both attach ``recording-sizes`` JSON to their Playwright results. These measure
fake-device output for a sanity check, not an upper bound on real recording sizes.
The demo checks exercise the default transport for the selected navigation mode.
The dedicated missing-recording fixtures cover asynchronous trial-failure handling.

The ``missing_chain_recording`` fixture exercises the asynchronous path with two
within-participant imitation chains. It drops the first upload and waits for the
real server deadline, then completes the unaffected chain, including playback of
its deposited parent recording. Final server assertions check that the missing
recording expired, its trial was not analyzed or reassigned, and the successful
chain finalized. The configured performance check still counts the failed trial:
two successful trials out of three yield a score of 2/3. Allow about two minutes
for this test; it does not shorten the production upload allowance.

The ``recording_document_loss`` checks reload and close the participant page while
an upload is pending. Browser-only bytes expire without failing a participant who
has no parent trial; fully received bytes are deposited after document loss.
Reload preserves the original deadline and adds no upload warning. A separate
case holds the upload while the normal Finish button reaches recruiter exit.
The private fixture exposes a read-only state endpoint for these checks; this
endpoint is not part of the PsyNet API.

The ``dual_recording_upload`` checks capture camera and screen together, hold both
uploads while the answer advances, then verify playable deposits for both sources.
A second case drops only the screen upload: camera playback survives, screen
playback becomes an explicit fallback at its deadline, and the participant can
finish. These use fake devices; the real screen-sharing chooser still needs a
manual check.

The ``recording_legacy_navigation`` check runs with
``inplace_timeline_transitions=false``. It verifies an actual document replacement
and a missing-video fallback without participant failure. This establishes loss
handling, not reliable upload delivery across full-page navigation. The upload
queue belongs to the old document, so unfinished bytes can be abandoned on every
such transition. Keep this distinction when evaluating default enablement.
When a test needs acceptance evidence across document replacement, capture it
with ``route.fetch()`` before fulfilling the browser response; Chromium can
discard response bodies during navigation. Assert the destination page before
reading the captured result.

The private ``asynchronous_recording`` fixture forces independent uploads even
when testing legacy document replacement. Its browser test holds a media request while
the accepted answer advances to an independent page, then releases the request
and checks playback after worker deposit. Submission tests cover rejected answers,
source validation, accumulated answers, named answer variables, and rollback.
Validation sees recording metadata with empty ID/URL placeholders; acceptance
installs the final references before saving the answer and calling
:meth:`~psynet.timeline.Page.on_complete`.

Recording submissions retry transient response failures up to three attempts,
with a ten-second request timeout per attempt. A browser-generated recovery
secret identifies the accepted page. Under the participant lock, a retry replays
its saved acceptance without reserving more assets, running completion hooks,
or advancing again. Replay preserves the original server time and upload
deadlines. It is limited to the same participant and original page while the
accepted successor remains current. Only a secret hash and token-free receipt
are stored; upload capabilities are derived from the browser-held secret.
The browser test deliberately loses a committed acceptance and verifies that
the recovered upload still produces playable video. This does not recover blobs
after reload or closing the document.

The document queue allows 256 MiB by default, enough for two recordings at the
128 MiB per-source limit. Before submitting, the browser checks both sources
against the remaining shared capacity, including uploads from earlier pages.
For example, with 200 MiB already queued, a new 40 MiB camera clip fits but a
second 40 MiB screen clip is recorded as unavailable. No queued clip is evicted.
Missing captures, oversized clips, queue exhaustion, and upload-module load errors
are recorded with the accepted answer. Independent navigation continues; the
server fails the affected trial at its existing deadline with the recorded reason.
Transport initialization has a five-second budget; both failed and stalled module
loads permit submission. The tests cover these paths and deadline behavior.

The optional background-recording demo exercises ordinary button answers, a
generated page with a repeated label, held uploads, and denied camera permission.
Its checks wait for captured bytes and accepted response receipts instead of
transient recording labels. See :doc:`/tutorials/modular_page` for manual steps.
Optional background assets do not enter trial dependency waits or fail trials.
The same demo compares optional and required background trials. Browser checks
hold both uploads while independent navigation continues; server checks verify
that required clips hold finalization, allow ordinary answer analysis, and fail
only the parent trial when missing. Real WebM deposit releases the finalization
gate without invoking answer analysis. Bots deliberately bypass required capture.

The asynchronous fixture also exercises :func:`~psynet.page.wait_for_recording`: a
missing non-trial upload reaches a fallback page at its real deadline and the
participant can finish. Successful uploads reach playable video. Unit tests cover
stalled processing and bounded legacy waits.

Before release, validate the default answer path against the existing video and
imitation-chain demos, browser-hosted jsPsych/Unity startup and same-session
capture, exports with unavailable assets, and SSH LocalStorage deployment. These
checks remain required after the implementation changes; earlier fixture results
do not establish that the new default or these integrations pass. Legacy mode
retains the existing answer-upload path.

For answer screen-recording pages, call the harness helper
``acceptAnswerScreenPermission(page)`` at the first known screen-capture step,
before waiting for task startup. Compatible later pages reuse the shared stream;
they do not show another dialog. The capture lifecycle spec also checks that
background and answer clips reuse a stream and each play independently.

The ``task_background_recording`` fixture uses the real UnityPage template with a
small engine stand-in and the repository's vendored jsPsych. It checks enabled
and skipped capture: task startup follows the permission decision, persistent
Unity pages produce separate recording identities, and a new jsPsych document
asks again. This does not replace a manual test with the deployed Unity game.

The provisional upload allowance uses a conservative 1 Mbit/s rate, 30 seconds
of overhead, and twice the estimated transfer time, bounded to 60–600 seconds.
For example, 1 MiB gets 60 seconds and 10 MiB gets 198 seconds. This is a planning
assumption, not an estimate of the average participant's connection. Ofcom's
`fixed broadband coverage report <https://www.ofcom.org.uk/phones-and-broadband/coverage-and-speeds/connected-nations-update-spring-2025>`_
uses 1 Mbit/s as its upload threshold for a decent connection; it does not establish
worldwide participant speeds. The cap can cut off large files on slow connections.

Reservations accept a size hint bounded by the server's upload-size limit and
an explicit timeout override. Without a size hint, the allowance uses that limit.
The clock starts when the response is accepted and includes queueing and retries;
it never restarts for another attempt. Successful server receipt starts a separate
processing deadline. When connecting multi-source recording controls, budget the
combined queued bytes rather than assuming each source gets the full bandwidth.

Dependent feedback, performance-check, and trial-selection waits include the
remaining upload and processing allowance, followed by their ordinary wait
budget. They snapshot this budget on entry; polling never extends it. A resolved
wait exits before checking for timeout, including when a participant returns to
an inactive tab after the recording has failed.

:func:`~psynet.page.wait_while` and :func:`~psynet.timeline.while_loop` accept
timeout callables evaluated once on entry. For example, an experiment can use
a participant-specific allowance without resetting it on each poll:

.. code-block:: python

    wait_while(
        lambda participant: participant.var.processing_pending,
        expected_wait=5,
        max_wait_time=lambda participant: participant.var.processing_allowance_seconds,
    )

The streaming endpoint requires the request socket exposed by Gunicorn or
Werkzeug to interrupt blocked reads at the deadline. Other WSGI servers receive
HTTP 503 until they have a supported deadline mechanism. A database expiry job
alone cannot release a worker blocked on a request body.

The clock schedules validation and deposit on a worker, then independently expires
overdue recordings. Received files use private shared storage:
``/var/lib/dallinger/media-uploads`` for SSH deployments and
``.deploy/media-uploads`` in the experiment directory for local deployments.
Dallinger mounts these directories in the web, worker, and clock containers.
Keep custom deployment layouts consistent with this requirement; a container's
temporary directory is not shared.

The receiver takes a nonblocking file lock per reservation on this shared volume;
concurrent attempts receive HTTP 429 without reading their bodies. A retry removes
partials left by a crashed receiver, and the clock removes abandoned partials
after expiry. Small lock files remain for the experiment's lifetime to keep their
identity stable across processes. This requires a shared filesystem that supports
POSIX file locks; an actual SSH deployment remains a validation requirement.

Files become available as assets only after validation and deposit succeed.
Validation uses ``ffmpeg`` to decode video within the processing deadline and
requires nonempty decoded output; a stream header alone is insufficient.
The server tests cover expiry during deposit and
failure of the affected trial in both within- and across-participant chains.


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
