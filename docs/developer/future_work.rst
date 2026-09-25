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
