.. _future_work:

Future work
===========

This page records ideas and small follow-ups for PsyNet maintainers, such
as limitations left by a merge request. It is not a roadmap or a commitment.

Each idea is a section with Date, Problem, and Idea subsections. Delete
the entry when it ships or is rejected. If it becomes a GitLab issue,
link the issue and shorten the write-up.

Payment event ledger
--------------------

Date
++++

2026-08-20

Problem
+++++++

Participant payment fields are a latest snapshot (``status``,
``base_payment``, ``planned_bonus``, ``bonus``, ``bonus_status``,
last-attempt detail). They overwrite. After a cap clip, a failed
bonus POST, a submission-complete replay, or a dashboard Pay / Dismiss,
it is hard to reconstruct what PsyNet decided versus what it transferred
versus what a human did.

Idea
++++

An append-only SQL table of payment events (a registered ``SQLMixin``
model, so it exports with ``psynet export``). Participant columns stay
the live state; events are history, not a second source of truth. Useful
kinds include issued completion code, decided / recorded amounts, cap
withhold or clip, bonus POST started, bonus POST result, Pay clicked,
dismissed, and platform poll. Commit "POST started" before the HTTP call
so a crash still leaves a row. That is also enough to show that a pay
request was started, without a separate in-progress ``bonus_status``.

Pre-built PostgreSQL driver
---------------------------

Date
++++

2026-09-24

Problem
+++++++

Dallinger depends on ``psycopg2``, which compiles against libpq. New users
must install libpq and edit their shell profile (``LDFLAGS`` and
``CPPFLAGS``) before PsyNet installs. Missing headers show up as
``pg_config executable not found`` or ``symbol not found in flat
namespace '_PQbackendPID'``. This is the most error-prone installation step
on macOS.

Idea
++++

Depend on ``psycopg2-binary`` (or ``psycopg[binary]``) in Dallinger so no
local libpq is needed. The installation docs could then drop the libpq
step entirely.

Installation checker
--------------------

Date
++++

2026-09-24

Problem
+++++++

Installation pages list many one-off steps, and users (and coding agents)
cannot easily tell which are done. ``psynet services check`` covers
PostgreSQL and Redis only. Other failures, such as macOS AirPlay Receiver
occupying the local server port, only appear when an experiment is run.

Idea
++++

A ``psynet doctor`` command that checks Python, uv, Git, Docker, Chrome,
services, and port conflicts, and prints the fix for each missing item.
The installation page would then reduce to "install these few tools, then
run ``psynet doctor``", and agents could follow the same checklist.

Copy demos without cloning PsyNet
---------------------------------

Date
++++

2026-09-24

Problem
+++++++

New users clone the PsyNet repository mainly to get the demos. This adds
a Git step, a large checkout, and version drift between the clone and the
installed package.

Idea
++++

A command such as ``psynet demo copy <name> <dest>`` that fetches a demo
at the tag matching the installed PsyNet version. Demos are currently
excluded from the published package, so the command would either download
them or the package would need to ship them. Cloning would then be needed
only by contributors.

Read demo code offline
----------------------

Date
++++

2026-09-30

Problem
+++++++

The installed package ships the documentation but not the demos, so a
coding agent without network access can't read a demo's ``experiment.py``.
It has to rely on the fragments that documentation pages quote.

Idea
++++

Ship each demo's source in the bundled documentation as text, or add a
``psynet demos show <name>`` command that prints it. Either would also serve
``psynet demo copy`` above if the package ships the demos.

Separate Docker layer for static stimuli
----------------------------------------

Date
++++

2026-09-25

Problem
+++++++

Stimulus sets in ``static/`` are baked into the experiment's Docker image,
and the default package-size limit is now 1024 MB to allow for that. The
experiment Dockerfile copies everything in one final layer
(``COPY . /experiment``), so any code change rebuilds and re-ships the layer
that contains the stimuli.

Idea
++++

Give ``static/`` its own Docker layer before the rest of the experiment, so
code-only changes reuse the cached stimulus layer. The final copy must then
leave out ``static/`` (for example with ``COPY --exclude``, which needs a
recent BuildKit), or the image stores it twice.

Code snapshots in Dallinger
---------------------------

Date
++++

2026-09-25

Problem
+++++++

Dallinger's ``setup_experiment`` writes a zip of the whole deployment package
to ``snapshots/<app-id>-code.zip`` when called with ``debug=False``. Only the
Heroku deployment paths do this; ``docker-ssh`` deployments do not. The
snapshot is read by Dallinger's own data export, which copies it into the
archive, and by OSF registration. PsyNet exports no longer include source
code. With larger ``static/`` folders, each snapshot would be as large as the
stimulus set.

Idea
++++

If Heroku deployment is being retired, check whether snapshots are still
needed at all, and remove them from Dallinger if not. If OSF registration
should keep working, produce the code archive there on demand instead.

Chain-level parameters instead of node context
----------------------------------------------

Date
++++

2026-09-25

Problem
+++++++

Chain nodes carry three records: ``seed`` (the input a node is built from),
``definition`` (the node's current state, derived from the seed), and
``context`` (parameters that stay fixed for the whole chain, copied from node
to node). ``context`` is hard to explain because it is attached to each node
but scoped to the chain. The ``staircase_pitch_discrimination`` demo notes
this in a comment.

Idea
++++

Let experimenters specify a list of chains, each with its own parameters,
instead of passing ``context`` to every start node. Nodes would then read
chain parameters from their chain, and ``context`` could be removed.

Stimulus space on the dense trial maker
---------------------------------------

Date
++++

2026-09-25

Problem
+++++++

In dense paradigms every :class:`~psynet.trial.dense.DenseNode` definition
must contain the ``dimensions`` of the stimulus space, even though all nodes
usually share the same space. The ``dense_color`` demo repeats the same
``**PARAMS`` in every node.

Idea
++++

Accept ``dimensions`` on :class:`~psynet.trial.dense.DenseTrialMaker`, used
by default for every condition, and keep per-node dimensions only as an
override. Each node would then hold only what distinguishes its condition,
such as ``{"adjective": "angry"}``.

URL stimuli in psynet-step
--------------------------

Date
++++

2026-09-25

Problem
+++++++

``StepTag`` in the external ``psynet-step`` package requires its stimuli as
assets and reads their ``.url``. Experiments that keep stimuli in
``static/`` must wrap each URL in an ``ExternalAsset``, as the ``step_tag``
demo does.

Idea
++++

Let ``StepTag`` accept plain URL strings as well as assets, so the demo can
pass ``/static/...`` URLs directly.

Automatic layout checks during bot tests
----------------------------------------

Date
++++

2026-09-28

Problem
+++++++

Bots take pages without displaying them, so ``psynet test local`` passes
experiments whose pages overflow a phone screen or push the response
controls below the fold. ``psynetLayout.check()`` detects these problems, but
it only runs from a hand-written Playwright walk, which few experiments have.
Two such bugs in built-in components (SurveyJS overflow on phones and broken
``LanguageVocabularyTest`` images) passed their bot tests and were only found
while taking documentation screenshots.

Idea
++++

Add ``psynet test local --check-layout``. After each page a bot takes, a
headless Chrome loads the same page and runs ``psynetLayout.check()`` at a
phone size (390×760) and a laptop size (1280×800); the test reports
violations by page label and fails if there are any. ``psynet audit
simulate`` could enable it so that audits record the result.

A manual check on 2026-09-28 (``simple_rating`` demo) confirmed the approach:

- ``GET /timeline?unique_id=...`` renders a participant's current page with
  no session cookie, so a separate browser can load a bot's page. Bots already
  make this request for every page (``render_pages=True``), so it is safe to
  repeat.
- ``check()`` returned no violations for the page as built, and reported
  ``no_horizontal_overflow`` and ``no_vertical_overflow`` when a wide element
  was added or the controls were pushed below the fold.

Details for the implementation:

- Use plain window sizes, not Chrome's mobile emulation. In mobile emulation
  a wide element enlarges the layout viewport, so ``window.innerWidth`` grows
  with the content and the horizontal check never fires.
- Audio pages show an "Are you ready?" overlay in a headless browser because
  no user gesture has happened; launch Chrome with
  ``--autoplay-policy=no-user-gesture-required``.
- Block the checking browser's requests to ``/response`` (and other endpoints
  that change state) so that page JavaScript, such as timed auto-submit,
  cannot advance the participant.
- Wait for page readiness, including media, before checking; the Playwright
  harness's readiness helper shows how.
- Selenium is already a Dallinger dependency and Chrome is already required,
  so no new dependency is needed. Keep the flag opt-in, because it adds a
  second or two per page.

Browser participants in performance tests
-----------------------------------------

Date
++++

2026-10-10

Problem
+++++++

``psynet performance-test`` bots use plain HTTP requests, so they skip
everything a browser adds: static files and media, requests to custom
routes from page JavaScript, and websockets at timeline holds and in live
multi-participant pages. Experiments that lean on these can pass a
performance test and still overload the server. Writing a Python websocket
client for the bots would cover only part of the gap and would duplicate
``psynet.js``.

Idea
++++

Let a performance test mix a few real browsers with the bots, for example
``--n-browsers 5``. Each browser runs a Playwright participant flow, such as
the experiment's ``tests/participant-flow.spec.js`` or a generic walk that
uses the bot responses, against the same server while the bots supply the
bulk of the load. The report would show browser and bot response times
separately. Headless Chrome needs a few hundred MB of memory per page, so
browsers stay a small share of the load; if the Playwright harness later
covers every experiment, it could replace the HTTP bots altogether.

Section dropdowns in the documentation header
---------------------------------------------

Date
++++

2026-09-28

Problem
+++++++

Each top-level documentation section (Design, Test, and so on) has an index
page that exists only to hold the section's table of contents. Clicking a
section in the header opens that index page, which lists the section's pages
without adding anything, instead of taking the reader to the content.

Idea
++++

Replace the header links for sections with dropdown menus listing the
section's pages, so a reader goes straight to the page they want. The PyData
theme has no built-in support for this, so it needs a small Sphinx extension
(roughly 60 lines) that reads each section's toctree during the build and a
custom ``navbar-nav`` template that renders Bootstrap dropdowns. The section
index pages would then be reached only from breadcrumbs, and could redirect
to the section's first page. The dropdowns also need to work in the
collapsed header on phones.

Stop the Prolific study when an experiment ends
-----------------------------------------------

Date
++++

2026-09-28

Problem
+++++++

PsyNet settles Prolific submissions itself. Participants who finish receive
an auto-approving completion code, and ``approve_hit`` completes submissions
that are still active or approves those already awaiting review. Researchers
therefore don't approve submissions by hand, which older lab documentation
told them to do.

Ending the study is still manual. Dallinger's ``ProlificRecruiter.close_recruitment``
deliberately does nothing, so the study stays open on Prolific after
recruitment finishes and even after ``psynet destroy ssh`` removes the app.
Participants who start it then reach an address that no longer exists. The
runbook warns researchers to stop the study on Prolific before destroying the
app, but this is easy to forget.

Idea
++++

Stop the Prolific study from PsyNet: offer it during ``psynet destroy ssh``
when the recruiter is Prolific (defaulting to yes), and add a dashboard button.
Prolific's API supports this with a ``STOP`` action on
``/studies/<id>/transition/``, the same endpoint Dallinger already uses to
publish. Stopping could also move into Dallinger's ``close_recruitment``,
guarded by a config option so existing behavior doesn't change silently.
Before relying on the automatic approval described above, confirm it once end
to end on a live Prolific study, since the documentation now depends on it.

Check EC2 provisioning settings before booting
----------------------------------------------

Date
++++

2026-09-28

Problem
+++++++

``dallinger ec2 provision`` checks that ``dashboard_user`` and
``dashboard_password`` are set in ``~/.dallingerconfig`` only after it has
booted the instance, resized its storage and connected over SSH (in
``prepare_docker_experiment_setup``). If either setting is missing,
provisioning stops with an assertion error and leaves a running instance
that is being billed, which the researcher then has to find and tear down.

Idea
++++

``server_pem`` is already checked before the instance boots. In Dallinger,
load the configuration and also check the dashboard settings and AWS
credentials at the start of ``prepare_instance``, before ``boot_instance``,
and raise a
``click.UsageError`` that names the missing keys. It's a short PR with a unit
test that mocks the EC2 client and asserts that no instance is booted when a
key is missing. Once it ships, update step 5 of the provisioning steps in
:doc:`/deploy/reference/aws_automatic_provisioning`.

Safer WebSocket elements
------------------------

Date
++++

2026-09-29

Problem
+++++++

Real-time experiments built on ``WebSocketElt`` have several rough edges
(see :doc:`/code/multiplayer/realtime_interaction`):

- The ``participant`` passed to ``handle_message`` comes from the ``sender``
  or ``participant_id`` field that the browser writes, and nothing checks it.
  Any browser can also connect to any channel, so private data has to go over
  an authenticated HTTP route instead.
- ``WebSocketElt`` can't be used on its own: its ``consume`` reaches
  ``Elt.consume``, which raises ``NotImplementedError``, so authors must also
  subclass ``NullElt``.
- Connect and disconnect events on ``dallinger_control`` never reach
  ``WebSocketElt`` handlers, although the ``WEBSOCKET_CHANNEL`` docstring
  suggests they do; authors override ``receive_message`` instead.
- A ``WebSocketElt`` on the ``dallinger_control`` channel is handled twice,
  because the experiment is subscribed to that channel twice.

Idea
++++

Give ``WebSocketElt`` ``NullElt`` behavior by default; add connect and
disconnect hooks; reject reserved channel names; and authenticate the sender
of each message, for example by having ``PsyNetWebSocketChannel`` send the
participant's ``unique_id`` and checking it before calling the handler.

Record sync groups on trials
----------------------------

Date
++++

2026-09-29

Problem
+++++++

Trials from trial makers with ``sync_group_type`` don't record which group
they were taken in. To pair up group members' trials, an analysis joins
``trial`` to ``participant_link_sync_group`` and, when participants can join
several groups, matches each trial to a group by comparing creation times
(see the "Group experiments" section of :doc:`/data/basic_data`). Also,
``ParticipantLinkSyncGroup.arrival_time`` is declared but never set, unlike
``ParticipantLinkBarrier.arrival_time``, so exports carry an empty column.

Idea
++++

Store ``sync_group_id`` on each trial when a trial maker with
``sync_group_type`` creates it, and either set
``ParticipantLinkSyncGroup.arrival_time`` when a participant joins a group or
remove the column. The data docs could then join trials to groups directly.

Learning tracks
---------------

Date
++++

2026-09-29

Problem
+++++++

The documentation used to include a "music perception track": a reading
order through the demos, pages and exercises for researchers running online
music perception studies. It was the only track, and it sat awkwardly among
the exercises, so it was removed. Its outline was:

#. Install PsyNet (:doc:`/install`) and create a first experiment
   (:doc:`/quickstart`).
#. Run ``demos/experiments/hello_world`` and ``demos/features/timeline``;
   match each demo's code to what a participant sees, then change some text.
#. Read :doc:`/design/timeline`, :doc:`/code/writing_a_timeline` and
   :doc:`/code/writing_pages`, then do the timeline exercise.
#. Run ``demos/experiments/audio`` (JSSynth chords and audio recording), then
   do the JSSynth exercise.
#. Read :doc:`/design/trials` and :doc:`/code/writing_a_trial_maker`, then run
   ``demos/experiments/trial``, ``trial_2``, ``trial_3`` and ``static_audio``.
#. Read :doc:`/code/project/classes_and_sqlalchemy`.
#. Apply ``demos/pipelines/simple_rating`` or ``demos/pipelines/tapping`` to
   your own stimuli.

``demos/experiments/vertical_processing`` is a complete music experiment.

Idea
++++

If there is demand, add a small "Learning tracks" section with several tracks
(for example music perception, language, visual perception), each a reading
order through existing pages, demos and exercises rather than new content.

Check documentation claims against live services
------------------------------------------------

Some documentation describes behaviour that can only be confirmed on a real
service. These claims were written from the code and the services' own
documentation, and haven't yet been checked end to end.

- **Prolific auto-approval** (:doc:`/deploy/recruiters/prolific`, "How
  PsyNet pays participants"): on a live study, check that clicking
  **Submit to Prolific** completes the submission with the auto-approve
  completion code, that Prolific approves it and pays ``base_payment``, and
  that any bonus arrives.
- **S3 Block Public Access** (:doc:`/code/stimuli_on_s3`): on a real bucket,
  check the ``put-public-access-block`` step and the bucket policy, and
  whether an account-level Block Public Access setting has to be turned off
  as well.
- **Unity C# snippets** (:doc:`/code/pages/unity_integration`): build them in
  a current Unity version and check that a Unity page exchanges data with
  PsyNet as described.

Mark launch-time assets as prepared stimuli
-------------------------------------------

Whether an asset is exported depends on whether it was deposited while PsyNet
prepared the deployment. Stimuli deposited later from the experiment
directory, such as those in ``on_launch`` hooks or the start nodes of
within-participant chains, are therefore exported with every export, often
once per participant. A public context manager (for example
``psynet.asset.preparing_for_deployment()``) would let authors mark such
deposits as prepared stimuli, and within-participant start nodes could use it
automatically.

Run several local experiments at once
-------------------------------------

Several local experiments can run at once when each terminal sets its own
``DATABASE_URL``, ``REDIS_URL``, ``base_port`` and
``dallinger_develop_directory`` (see :ref:`running_several_local_experiments`);
launches then stop only workers and browsers that use their own database. CI
uses the same isolation for parallel test slots, and local test sessions set
it up automatically (``psynet.isolated_environment``). Two gaps remain. Every
run still needs its own Redis server, because Redis pub/sub channels (PsyNet's
timeline-hold wakes and Dallinger's chat channels) are shared by all database
numbers on a server; prefixing channel names with the database identity in
both packages would let runs share one server. And ``psynet debug local
--isolated`` picks a free slot for a debug server, but other commands, such as
``psynet deploy local``, still need these variables set by hand.

SameSite dashboard login cookies and POST-only Dallinger actions
----------------------------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

PsyNet's dashboard actions are now POST-only, and
``Experiment.before_request`` refuses cross-site POST, PUT, PATCH and DELETE
requests to the dashboard or made with the dashboard login, using
``Sec-Fetch-Site`` and then ``Origin``/``Referer``. This is the only layer of
protection: the experiment server still sets the Flask session and
Flask-Login "remember me" cookies without a ``SameSite`` attribute (Chrome
treats that as ``Lax``; other browsers may not), and some Dallinger dashboard
actions, such as ``/dashboard/logout``, still change state on GET.

Idea
++++

In Dallinger, where the Flask app is configured, set
``SESSION_COOKIE_SAMESITE`` and ``REMEMBER_COOKIE_SAMESITE`` to ``"Lax"``
(``"Strict"`` would drop the login when a researcher follows a dashboard link
from Slack or email) and move its remaining state-changing GET routes to POST.
Participants don't rely on the Flask session, so this should not affect
experiments embedded in recruiter iframes; check that before changing it.

Use Dallinger's app addresses and app-name checks for SSH commands
------------------------------------------------------------------

Date
++++

2026-10-21

Problem
+++++++

PsyNet works out a docker-ssh app's address itself. ``_remote_public_origin``
and ``_caddy_site_origin`` in ``psynet/command_line.py`` parse the server's
Caddy files (released Dallinger's root ``Caddyfile``, ``root.d/<app>`` and
``caddy.d/<app>``), about 70 lines that copy Dallinger's server layout into
PsyNet. PsyNet also applies Dallinger's Heroku-era ``verify_id`` to
``deploy ssh``, ``debug ssh`` and ``performance-test ssh``, so
``deploy ssh --update`` and ``performance-test ssh`` can't target an app on
the server's own host, whose name starts with ``dlgr-``.

Idea
++++

Once PsyNet pins a Dallinger release that includes
`Dallinger PR #10163 <https://github.com/Dallinger/Dallinger/pull/10163>`_:

- Drop ``_remote_public_origin`` and ``_caddy_site_origin``.
  ``_ssh_dashboard_endpoint`` can take the address from Dallinger, for example
  ``next((a.public_origin for a in get_apps(server) if a.name == app), None)``.
  Keep the local launch note first and the ``https://<app>.<server>`` guess
  last. The layout cases in ``tests/isolated/test_ssh_export_origin.py`` can
  go too, because Dallinger tests them.
- Stop applying ``verify_id`` to the SSH commands, and use
  ``_verify_existing_ssh_app`` as the single ``--app`` check for every SSH
  command. Dallinger accepts ``--app dlgr-…``: a new name deploys to a
  subdomain, and an existing app on the server's own host is refused without
  ``--update`` and updated in place with it. Heroku commands keep
  ``verify_id``.
- PsyNet's own new-deploy check (``get_apps`` followed by "App with name …
  already exists") runs before Dallinger's. It could add the same
  ``--update --app <app>`` hint for an app on the server's own host, or leave
  that case to Dallinger.
- Keep ``_require_ssh_apps_exist``'s ``dlgr-<first 8 characters>`` suggestion
  for a full experiment UUID; that is PsyNet's own help.

Pin a Dallinger that checks Redis before clearing the database
--------------------------------------------------------------

Date
++++

2026-11-02

Problem
+++++++

PsyNet pins Dallinger master ``96e5cf8eb``. If Redis is down, that
Dallinger's ``init_db(drop_all=True)`` drops the tables before it fails to
clear the real-time sessions, so ``psynet prepare`` leaves the database
without its tables.

Idea
++++

Move the pin to a Dallinger that includes
`Dallinger PR #10251 <https://github.com/Dallinger/Dallinger/pull/10251>`_,
for example at the next Dallinger release.

Reject reserved SSH app names before contacting the server
----------------------------------------------------------

Date
++++

2026-11-02

Problem
+++++++

``_pre_launch`` calls Dallinger's ``_check_app_name_not_reserved`` only after
``_abort_if_app_exists`` has connected over SSH. With ``--app logs``, an SSH
failure hides the reserved-name error.

Idea
++++

Run the check as soon as an explicit ``--app`` is known, and again after
``_default_ssh_app_name`` when ``--app`` was omitted.

Show real-time runners in ``psynet services list``
--------------------------------------------------

Date
++++

2026-11-02

Problem
+++++++

``psynet/service_usage.py`` treats only ``dallinger_heroku_*`` processes as
Dallinger servers, so a leftover ``dallinger_realtime`` runner isn't
attached to its session. Cleanup already stops these runners.

Idea
++++

Also match ``dallinger_realtime``, or reuse Dallinger's
``local_worker_processes`` as the cleanup code does.

Check for the Heroku CLI in every Heroku command
------------------------------------------------

Date
++++

2026-11-02

Problem
+++++++

Only ``psynet deploy heroku`` and ``psynet debug heroku`` stop early with
install instructions when the Heroku CLI is missing. ``export heroku``,
``destroy heroku``, ``db heroku`` and ``experiment-variables heroku`` still
fail with Dallinger's "You are not logged into Heroku." or a
``FileNotFoundError``.

Idea
++++

Move the ``shutil.which("heroku")`` check into a helper that every Heroku
code path calls before using ``HerokuApp``.

Supported Node in the experiment ``Dockerfile``
-----------------------------------------------

Date
++++

2026-11-02

Problem
+++++++

The experiment ``Dockerfile`` template, which also defines development
environments such as Codespaces, installs Debian trixie's ``nodejs``
package, Node 20.19. Node 20 reached end of life in April 2026.

Idea
++++

Copy ``node`` and ``npm`` from the official Node image that the root
``Dockerfile`` copies from, so that both images use the Node release
set by its ``NODE_VERSION`` build argument.

Remove obsolete warning filters
-------------------------------

Date
++++

2026-11-02

Problem
+++++++

``tests/isolated/test_warnings.py`` still filters warnings from the Heroku
CLI and Node, which local launches no longer produce now that they use
honcho. Its broad ``DeprecationWarning:`` filter can hide real warnings.

Idea
++++

Remove the Heroku and Node patterns, check the test still passes, and
narrow the remaining filters.

Incognito warning when detection is unavailable
-----------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

With ``force_incognito_mode = true``, browsers where incognito detection
fails (such as Firefox) are rejected with a message asking the
participant to open an incognito window. Now that ``force_google_chrome``
defaults to ``false``, Firefox participants are admitted otherwise, and
following that instruction in a private Firefox window shows the same
message again.

Idea
++++

When ``browser.incognitoDetectionFailed`` is true, also suggest opening
the experiment in an incognito window of a browser where detection works,
such as Chrome.

Single permission prompt and retry in the browser capability check
--------------------------------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

With ``browser_capabilities = {"microphone", "camera"}``, the capability
check calls ``getUserMedia`` once per device, so the browser can ask twice
although the intro page promises one request. A participant who dismisses
a prompt by accident goes straight to the unsuccessful end page, and a
participant who ignores the prompt waits on the spinner indefinitely.

Idea
++++

Request audio and video in one ``getUserMedia`` call when both are needed,
and offer a retry button on the failure page before ending the experiment.

Name every failed capability on the browser capability failure page
--------------------------------------------------------------------

Date
++++

2026-11-04

Problem
+++++++

``browser-capability-check.js`` stops at the first failing capability,
in alphabetical order, so the failure page names only that one. In a
manual test with ``browser_capabilities = {"microphone", "camera"}``
and both devices denied, the page said only "We were unable to access
your camera", so a participant might fix the camera and fail again on
the microphone.

Idea
++++

Run every check, collect all failures, and list each failed capability
on the failure page.

Browser-neutral incognito instructions for Chromium browsers
------------------------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

``browser.isChrome`` in ``browser-detect.html`` now covers every
Chromium-based browser, so Edge, Brave and Opera users who must use
incognito mode get instructions that name Chrome.

Idea
++++

Rename the flag to ``isChromium`` and use browser-neutral wording when
``browser.name`` is not ``Chrome``.

Re-host pre-screen stimuli under neutral names
----------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

The built-in pre-screens serve their stimuli under opaque ``/asset/<token>``
URLs, but the original files are still public under paths that name the
answer, such as ``images/<word>/correct.png``. A scripted cheater can
download them and match the bytes PsyNet serves. The server also fetches
each file from S3 on every request, without caching. The ``/asset/<token>``
route holds its database session while it downloads (with a 30-second
timeout), so a slow S3 response keeps a database connection busy and many
concurrent stimulus requests could exhaust the connection pool.

Idea
++++

Re-host the files under neutral names in a location participants can't
list, and serve them as ordinary assets (or cache the on-demand
downloads) so that stimulus requests no longer wait on S3. Until then,
the route could read what it needs from the database and release the
session before downloading.

Add a public way to proxy a remote stimulus
-------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

The built-in pre-screens hide answer-revealing stimulus URLs with the
internal helper ``_opaque_media_asset``, which wraps a remote file in an
:class:`~psynet.asset.OnDemandAsset` that the server downloads. Experiment
authors with the same problem have no public equivalent, yet the
pre-screening tutorial shows this helper.

Idea
++++

Add a public constructor such as ``OnDemandAsset.from_url(url)`` that
serves a remote file under an opaque ``/asset/<access_token>`` URL, use it
in the built-in pre-screens and document it in the tutorial.

Give Lucid participants a secret ``unique_id``
----------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

The Lucid recruiter sets the worker, assignment and HIT ids all to the
respondent's RID, so a Lucid participant's ``unique_id`` is ``RID:RID``.
Anyone who knows the RID can open ``/timeline?unique_id=RID:RID`` and act
as that participant, or terminate them through ``/terminate_participant``.

Idea
++++

Generate the assignment id on the server when a Lucid participant is
created, and update the Lucid callbacks that read ``assignment_id`` as the
RID to use the stored RID instead.

Stop excluding ``static/assets`` from deployments and Git
---------------------------------------------------------

Date
++++

2026-11-03

Problem
+++++++

The stock ``deploy.toml`` excludes ``static/assets`` because older PsyNet
versions left a link to local asset storage there, and deployment plans
reject links; the stock experiment ``.gitignore`` also ignores it as
generated content. PsyNet no longer creates that link, so these exclusions now only
leave an author's own ``static/assets`` folder untracked and undeployed
without a warning.

Idea
++++

Once few experiments still have the link, remove the exclusion from the
``deploy.toml`` and ``.gitignore`` templates, and have debug and deploy
commands remove a leftover link (or point to ``psynet scripts prune``) before
they build the deployment plan.

Tie chat ``leave_room`` to the page that sent it
------------------------------------------------

Date
++++

2026-11-04

Problem
+++++++

``EnableChatrooms`` handles ``leave_room`` by deactivating every active
membership the participant has in that room, whatever page sent it. If a
second tab on the same page closes, the participant drops out of the room
in the tab still open, and the widget silently loses the lines they send.

Idea
++++

Send the page's ``page_uuid`` with ``join_room`` and ``leave_room`` and
deactivate only the membership for that page. Optionally reply to a
non-member's message so the widget can rejoin or keep the draft.

Refuse non-object JSON bodies on ``/response``
----------------------------------------------

Date
++++

2026-11-04

Problem
+++++++

``/response`` returns a 400 for a ``page_uuid`` that isn't a string, but a
JSON body that isn't an object, such as ``[]``, still fails with a server
error because the route calls ``json_data.get``.

Idea
++++

Return the same 400 when the decoded body isn't a ``dict``.
