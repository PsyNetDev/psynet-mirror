Audit reference
===============

An **experiment audit** is a portable ``audit/`` folder that packages evidence
that an experiment was implemented and validated. It records artifacts, checks,
and blockers for human inspection, then renders a static HTML site.

The audit CLI can run participant simulations and local performance tests,
write their canonical evidence into the packet, and update ``audit.json``.
Other evidence is collected separately and marked present once ready.

**Default layout:** run the CLI from the experiment directory. The audit always
lives at ``./audit/``. Experiment source is that experiment directory (the parent
of ``audit/``). If ``experiment.py`` is in a subdirectory, set
``experiment.entry_point``. Commands take no packet path and no
``--experiment`` option. ``psynet audit simulate`` writes the simulated export
directly into this experiment's ``./audit/``; pass ``--n-bots N`` to override
``Experiment.test_n_bots`` for that run. Running from a directory named
``audit`` is an error.

.. note::

   Older packets with ``audit.json`` in the experiment root must be moved to
   ``./audit/``. ``experiment.source_base`` and ``experiment.source_path`` are
   no longer used.

Audit support ships with PsyNet but requires the full experiment runtime
(``psynet[experiment]``), including Dallinger and the audit HTML render
dependencies. Participant video validation also requires ``ffprobe`` from
``ffmpeg``.

.. code-block:: bash

   psynet audit init
   psynet audit simulate
   psynet audit performance-test
   psynet audit validate
   psynet audit mark-present <artifact_id>
   psynet audit render
   psynet audit serve

* ``init`` creates a starter ``audit/`` directory whose required-but-missing
  artifacts are covered by starter blockers. Validate can pass on this sparse
  starter; that means the packet is coherent, not that the experiment is ready.
* ``validate`` checks the manifest structure, required artifact files, blocker
  coverage, video limits, and notebook JSON readiness. It reports how many
  blockers are still recorded and that readiness may still be incomplete.
  Executed notebooks may be up to 10 MB, accommodating embedded figures while
  keeping packet validation bounded.
  Warnings (non-fatal) include a participant video whose audio track is
  silent (peaks below -60 dBFS), a still-placeholder ``implementation.summary``
  and ``TIMELINE.md`` lines that look like entries but were ignored because the
  actor tag was not one of ``agent-start``, ``agent``, ``agent-stop``,
  ``manual``, or ``system``. The starter TODO summary is omitted from the
  rendered page title until rewritten.
* ``mark-present`` sets an artifact to ``present``, verifies the file or
  non-empty directory exists and passes the same video/notebook checks as
  ``validate``, removes matching
  blockers, and updates ``updated_at``. Use this after you add a real file
  instead of hand-editing status fields.
* ``render`` validates first, then builds a self-contained static site under
  ``audit/site/``. Pass ``--allow-invalid`` only when you need to preview a
  broken manifest. Text previews are truncated after 100 KB. Rendered notebook
  previews have a separate 10 MB allowance for embedded figures and other rich
  output. The page header shows the experiment's short Git commit, with
  ``-dirty`` when files outside ``audit/`` have uncommitted changes. Set
  ``experiment.git_commit`` in ``audit.json`` to show a fixed value instead,
  for example when rendering outside the experiment's Git repository.
* ``serve`` hosts that static site over HTTP (default ``http://127.0.0.1:8765/``).
  Pass ``--render`` to rebuild first. It does not create a public tunnel.
  Binding to a non-localhost host (for example ``--host 0.0.0.0``) exposes the
  rendered audit, including any data exports and executable notebook HTML, to
  the network without authentication.

Rendered Markdown and notebook Markdown outputs support MathJax equations.
Use ``$...$`` or ``\(...\)`` for inline mathematics and ``$$...$$`` or
``\[...\]`` for display mathematics. The renderer packages MathJax with the
audit site, so equations work offline. Escape a literal currency symbol as
``\$`` when another dollar sign occurs later in the same block.

Status conventions
------------------

* Required artifacts that are not ready should use ``status: "blocked"`` plus a
  matching blocker (``reason`` + ``next_step``).
* Optional artifacts may use ``status: "missing"`` without a blocker.
* Use ``present`` only when the file exists and is ready to inspect.
* Use ``not_applicable`` when the experiment design makes the artifact
  unnecessary.

Checks and blockers
-------------------

There is no command for adding checks or blockers; edit ``audit.json``. Each
entry in ``checks`` records one validation step:

.. code-block:: json

   {
     "id": "participant_walk",
     "title": "Playwright participant walk",
     "status": "pass",
     "command": "npx playwright test tests/participant-flow.spec.js"
   }

``id`` (lowercase words joined by underscores), ``title`` and ``status`` are
required. ``status`` is ``pass``, ``fail``, ``warning`` or ``not_run``. The
Checks panel shows the status, the title and the optional ``command``; other
fields are allowed but not shown.

Each entry in ``blockers`` needs ``artifact_id`` (an artifact declared in
``artifacts``), ``severity``, ``reason`` and ``next_step``. Use ``"severity":
"error"`` when the evidence is missing or unusable; starter blockers use it.
Use ``"warning"`` for a limitation of evidence that is still worth
inspecting, such as a participant video without audio when audio capture
failed. Validation treats both
severities the same. ``mark-present`` removes an artifact's blockers, so add
a warning after marking the artifact present.

Bundle layout
-------------

.. code-block:: text

   my_experiment/
     experiment.py
     audit/
       audit.json
       PROMPT.md
       PLAN.md
       TIMELINE.md
       REPORT.md
       artifacts/
       logs/
       simulate/
         analysis/
           analysis.ipynb
           simulated_export/
         design/      # optional design simulation
           simulation.ipynb
           run.json
           results.csv
       site/          # generated by render; usually not committed

Stock ``deploy.toml`` excludes the whole ``audit/`` tree from debug staging
and remote deployment packages. Keep participant-facing code beside
``experiment.py``. Design-simulation scripts under ``audit/`` run locally.

``audit.json`` is the machine-readable manifest. Markdown section files provide
audit context. Incomplete required artifacts must be represented by blockers
rather than hidden by rendering.

.. _audit_design_simulation:

Power analysis
--------------

A design simulation runs the planned experiment many times on simulated
participants, outside PsyNet, to choose the numbers of participants, stimuli
and trials. PsyNet has no command that runs it; the experiment's own script
does, and PsyNet only displays the results. ``psynet audit simulate`` is a
different step: it runs the experiment's bots with ``psynet test local`` and
saves their export under ``simulate/analysis/simulated_export/``, marked
present, for the analysis notebook.

``psynet audit init`` creates ``simulate/design/`` and declares three optional
artifacts there, all with status ``missing``:

* ``simulation_notebook``: ``simulation.ipynb``, the executed report;
* ``simulation_run``: ``run.json``, the run's provenance;
* ``simulation_results``: ``results.csv``, the per-scenario results the
  notebook reads.

Leave them ``missing`` when there is no design simulation. Once the files
exist, mark each one present with ``psynet audit mark-present``, which also
checks that the notebook is valid. The Power analysis section, which follows
the Plan, then shows a
summary of ``run.json`` (its ``method``, ``command``, ``replicates``,
``result_row_count``, ``created_at`` and ``note`` fields, when present), the
notebook's saved outputs, and the other files in the directory. The notebook
is not re-executed, so execute it before adding it. The
:doc:`/skills/power-analysis` skill describes a recommended way to produce
these files.

Rendered sections
-----------------

The rendered site starts with an audit completeness summary, followed by the
sections listed in ``audit.json`` (see :doc:`/test/audits` for the starter
sections). Each section's ``kind`` selects one panel:

* ``screenshots``, ``participant_video``, ``monitor``, ``performance``,
  ``data``, ``simulation``, and ``analysis`` each render their corresponding
  evidence;
* ``simulation`` is optional: it renders
  ``simulate/design/simulation.ipynb`` and its run provenance. The notebook
  contains a Power analysis section and may contain an Adaptive procedure
  section;
* ``analysis`` renders ``simulate/analysis/analysis.ipynb`` and lists files in
  the adjacent ``simulated_export/`` directory;
* ``source`` renders ``experiment.py`` (or ``experiment.entry_point`` when
  configured) from the experiment directory as Python source, followed by the
  experiment's other Python modules. Hidden folders, ``audit/``, ``tests/``,
  ``static/``, ``node_modules/``, ``test.py`` and empty ``__init__.py`` files
  are left out;
* ``files`` lists the remaining artifacts; data exports are not repeated here
  because they have their own download panel;
* ``evidence`` renders every evidence subsection in a single panel and remains
  supported for older packets;
* ``checks`` panels are omitted when no checks are recorded.

The ``screenshots`` panel shows the images under ``artifacts/screenshots/``.
Their captions come from the optional ``artifacts/screenshots/manifest.json``,
whose keys are paths relative to ``artifacts/`` (a leading ``artifacts/`` is
also accepted):

.. code-block:: json

   {
     "captions": {
       "screenshots/01-consent.png": "Consent page.",
       "screenshots/02-rating-trial.png": "First rating trial."
     }
   }

A screenshot without a matching key is captioned with its file name, so a key
such as ``"01-consent.png"`` is ignored.

Profiles and extensions
-----------------------

Manifests may declare:

.. code-block:: json

   {
     "profile": "psynet.core",
     "extensions": []
   }

* ``profile`` defaults to ``psynet.core`` when omitted.
* The starter packet includes a ``plan`` section pointing at ``PLAN.md``. That
  section is **recommended** for agent-led implementation audits but **optional**
  for retrospective audits created after the experiment is already built. Remove
  the section, hide it with ``"display": false``, or leave the starter placeholder.
* ``extensions`` is a list of opaque extension ids (for example
  ``psynetskills.challenge``). Extensions add more ``sections`` rows that still
  use **core** section kinds (``markdown``, ``files``, ``json``, and so on).
* Core ``psynet audit validate`` / ``render`` ignore unknown extension ids.
  Documented external ids such as ``psynetskills.challenge`` are silent;
  other unknown ids may print a warning. Unknown section **kinds** remain a
  validation error.
* PsyNet does not load extension code. External tools such as PsyNetSkills
  read the declared extension ids and apply their own rendering on top.

Worked example: record a log
----------------------------

.. code-block:: bash

   cd my_experiment
   psynet audit init
   printf 'local test ok\\n' > audit/logs/local-test.log
   # add a log artifact to audit.json (or extend an existing one), then:
   psynet audit mark-present my_log --path logs/local-test.log
   psynet audit validate
   psynet audit render

Python API
----------

Shared helpers live under :mod:`psynet.audit` (model classification, HTML
rendering, and artifact publication). Publishing monitor snapshots copies
static assets from the installed Dallinger package
(``dallinger/frontend/static``).

The rendered site treats the experiment's notebooks, Markdown reports, and the
PsyNet audit templates as trusted author content. Notebook HTML and SVG outputs
are included as produced, including any scripts they contain, so opening an
audit in a browser runs that content with the viewer's privileges. Markdown
files are parsed as Markdown and do not interpret raw HTML. Credential
redaction for published logs and snapshots is separate from that rendering.
Do not bind ``psynet audit serve`` beyond localhost unless every viewer is
trusted with that notebook content.

Monitor snapshots
-----------------

``monitor.html`` snapshots are rewritten for static viewing and their
``/static/...`` assets are copied from the installed Dallinger frontend. PsyNet
does not vendor a second copy of those files.
