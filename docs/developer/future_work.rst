.. _future_work:

Future work
===========

This page records **unconfirmed** ideas for PsyNet maintainers. It is not a
roadmap, not a commitment, and not a substitute for GitLab issues.

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

Drop the Heroku CLI requirement
-------------------------------

Date
++++

2026-09-24

Problem
+++++++

``psynet test local`` uses the Heroku CLI only for its ``heroku local``
process manager. Users have to install a non-Python tool for a platform
they will not deploy to, and the docs have to explain why.

Idea
++++

Replace ``heroku local`` in Dallinger with a Python process manager
installed as a normal dependency, so the Python environment is the only
requirement for local testing.

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

Local experiments share port 5000, the PostgreSQL database, Redis and
Dallinger's ``/tmp/dallinger_develop`` folder, and each launch stops every
PsyNet worker process on the machine, so a second experiment breaks the first.
The documentation and Agent Skills tell users and agents to run one at a
time. Proper isolation would need launches to stop only their own workers
(for example by marking processes with the experiment directory), a refusal
to rebuild a development folder another experiment is serving from,
``base_port`` honoured in the default debug mode, per-experiment databases or
Redis databases, and Chrome cleanup limited to the experiment's own windows.
A first implementation was prototyped and then reverted in
`!1253 <https://gitlab.com/PsyNetDev/PsyNet/-/merge_requests/1253>`_, as too
large for a bug-fix merge request.
