.. highlight:: shell

======================
Updating documentation
======================

To update PsyNet's documentation, work from the root of your PsyNet source checkout, e.g.:

.. code-block:: console

  cd ~/PsyNet

The ``docs`` directory and its subdirectories contain files in `rst` format which stands for `reStructuredText`. See `this primer`_ which introduces the most basic syntax elements of `reStructuredText` documents. For a detailed reference check out the `complete technical specification`_.

.. _this primer: https://docutils.sourceforge.io/docs/user/rst/quickstart.html
.. _complete technical specification: https://docutils.sourceforge.io/docs/ref/rst/restructuredtext.html

Published page URLs are linked from elsewhere, so when you move, rename, or
delete a page, add an entry to ``docs/redirects.json`` mapping the old page
path to its replacement (both without the ``.rst`` suffix). The docs build
warns if a redirect target is missing or an old path still exists.

Write the PsyNet install step as a line containing only
``uv pip install psynet``. The build replaces each such line with a command
that installs the PsyNet version the docs were built from:
``uv pip install "psynet==X.Y.Z"`` when a release tag points at the built
commit, otherwise an install of that exact commit from GitLab. Other install
lines, such as ones with extras, are left unchanged. The replacement is
``_pin_install_commands`` in ``docs/conf.py``.

Once you have made changes to one or more `rst` files compile them into `html` files by executing:

.. code-block:: console

  psynet dev docs make

This uses a serial Sphinx build by default to keep generated HTML deterministic. To speed up local preview builds, pass ``--jobs auto``.

For an automatically rebuilding local preview, run:

.. code-block:: console

  psynet dev docs make --live-preview

This serves the HTML documentation with ``sphinx-autobuild`` and opens it in your browser. By default it uses port ``8000``; pass ``--port`` to use a different port.

Adding or deleting files additionally requires a clean build for the links in the menu to be updated accordingly:

.. code-block:: console

  psynet dev docs make --clean

To open the generated documentation in your browser after a successful build, run:

.. code-block:: console

  psynet dev docs make --open

CI runs a strict HTML build and then a link check in one job on every merge
request. Before submitting documentation changes, run the same commands locally.
Treat Sphinx warnings as errors with:

.. code-block:: console

  psynet dev docs make --strict

To check documentation links, run:

.. code-block:: console

  psynet dev docs linkcheck

This is a wrapper around Sphinx's ``linkcheck`` builder — the same target as
``psynet dev docs make linkcheck``.
Sphinx fetches the URLs in the documentation and reports the ones that fail.
The PsyNet command shows progress during that run, then reprints the failures
grouped by category (for example 404s, missing anchors, SSL errors, and
connection errors).

Only internal links, missing anchors, and pages not found (404 or 410) make
the command fail, because those mean the documentation itself needs fixing.
Other failures, such as 403s, timeouts, and SSL or connection errors, usually
come from the remote site or the network, so they are reported without
failing. Pass ``--strict`` to fail on every broken link.

Checks against external sites are unreliable in CI. The ``docs`` job fetches
every external link in every merge request pipeline, so the same sites
receive requests from GitLab's shared runners many times a day. Some sites
rate-limit or block that traffic and answer with 403s or dropped
connections, and runners sometimes lose network access to a host for a
while. A link that works in a browser can therefore fail in CI, and such a
failure would block a merge request that has nothing to do with the link.

The strict check still matters, because a link that is blocked or
unreachable for weeks may have moved or gone for good. It therefore runs
once a week rather than on every pipeline. Running it rarely keeps the
request volume low, and a failure that persists across weekly runs is
worth investigating. Because it runs on a schedule, its failures don't block
anyone's merge request. When the weekly job fails, open the link in a
browser. If it works there but keeps failing in CI, add it to
``linkcheck_ignore`` in ``docs/conf.py``. Otherwise, update or remove it.

The ``docs_linkcheck_strict`` CI job runs the strict check on ``master``. It
runs only in pipelines from a weekly GitLab pipeline schedule (*Build >
Pipeline schedules*) on ``master`` that sets the variable ``WEEKLY_LINKCHECK``
to ``1``, for example with the cron expression ``0 3 * * 1``. Those pipelines
run no other jobs. Don't also set ``NIGHTLY_BENCHMARKS`` on that schedule. As
with the nightly benchmark schedule, the schedule's owner needs the
Maintainer role to run pipelines on ``master``.

The command deletes ``docs/_build`` first by default. For faster local reruns, pass
``--no-clean``. Extra Sphinx flags can be passed with ``--sphinx-option``.

Link internal pages with Sphinx roles such as ``:doc:`` or ``:ref:``, not raw
``.html`` paths. The published HTML site can resolve a relative path such as
``../tutorials/setting_up_slack.html``, but linkcheck looks for that ``.html``
file next to the ``.rst`` source and reports it as broken.

Writing pages
-------------

- If a page has an introduction, make it a complete sentence. Write "This
  section covers the timeline and trials", not "The timeline and trials".
- Leave out introductions that only describe what the reader can already
  see, such as "Each card below describes…". Start with the content.
- Keep contributor instructions off public-facing pages. They belong on
  developer pages such as this one.
- State facts directly. Describe what something is, what it contains and how
  to use it, without framing sentences ("An experiment can run without
  errors and still…"), rhetorical questions or slogans.
- Don't write navigation as prose, such as "See X for this, Y for that, and
  Z to try it yourself". Order pages so that the sidebar and the *Next* link
  lead to the natural next page, and link inline only where a reader needs
  that page at that point.
- Put details that only apply inside a lab with shared accounts, servers or
  conventions in a ``.. lab-note::`` box. It renders with the title "In a lab"
  so other readers can skip it.

Research papers
---------------

:doc:`/introduction/research` is generated from
``docs/introduction/research.bib``. To add a paper, paste its BibTeX entry into
that file and list the matching techniques in its ``keywords`` field, for
example ``keywords = {chains, recording}``. The allowed tags are the keys of
``TECHNIQUES`` in ``docs/_ext/research_list.py``; the build warns about
entries with missing or unknown tags. Techniques without papers are left off
the page. Gallery cards that mention papers use
``.. example-publications:: <tag>``, which lists each paper as an author–year
link to its URL or DOI.

Gallery screenshots
-------------------

The demo carousels on :doc:`/introduction/applications` show phone-sized
screenshots from ``docs/_static/images/gallery/``. Each carousel lists demo
paths, and a demo without a screenshot shows a placeholder. Hover captions
come from ``CAPTIONS`` in ``docs/_ext/demo_carousel.py``. To add or refresh
screenshots, add a step for the demo to
``docs/scripts/gallery_screenshots/gallery.spec.js``, add a caption, and run:

.. code-block:: console

  npx playwright test -c docs/scripts/gallery_screenshots --grep <demo>

The script launches each demo with ``psynet debug local``, so a demo that no
longer displays well on a phone shows up in its screenshot.

Concept pages and code pages
----------------------------

The documentation separates concepts from code. :doc:`/design/index`
explains ideas without Python code, for someone specifying an experiment or
reviewing an implementation. :doc:`/code/index` shows how those ideas are
written in ``experiment.py``. :doc:`/test/index`, :doc:`/deploy/index` and
:doc:`/data/index` are task-oriented: they lead with commands and use short
Python snippets only where the task needs them, such as bot hooks, recruiter
settings or ``get_basic_data``. When a concept page has a code
counterpart, give both pages the same section headings so readers can move
between them, and end the concept page with a ``seealso`` link to its code
page.

The documentation describes what PsyNet provides and how it works.
Recommended workflows and research methodology built on PsyNet, such as
adaptive designs and design simulation, belong in the Agent Skills under
``.cursor/skills/experiment/``, which are published in the Agent Skills section of
this site. Skills are read by people as well as agents, so write them with
clear steps and checklists and explain what a person needs to know. When a
skill relies on a PsyNet fact, such as a hook, a command or an audit file,
document the fact here and link to it from the skill; when a docs page
mentions a workflow, link to the skill rather than repeating it.

On concept pages:

- Write so the page reads completely without code. Use at most a tiny
  illustrative snippet.
- Use bold for key terms, not API links. Links to the API reference belong on
  the code page.
- Describe what experimenters decide and what PsyNet does for them. Leave out
  automatic behavior the reader never acts on, and describe the usual path
  first. For example, most participants who leave early do so because PsyNet
  fails them after a screening task or performance check, not because the
  experimenter placed an end page.
- Do not assume participants are paid. Write "if the experiment pays
  participants" or "where relevant".
- Where there are checks a reviewer might not think of, end with a "What to
  check when reviewing" list. Leave it out if every item would be obvious.

On code pages:

- Link each class and function to the API reference with ``:class:``,
  ``:func:``, or ``:meth:``.
- Take worked examples from tested demos with ``literalinclude`` (preferably
  ``:pyobject:``) rather than pasting them, so they cannot drift from the code.
- Keep other snippets short, and check argument names and signatures against
  the source.

The generated HTML from ``psynet dev docs make`` is written to
``docs/_build/html/index.html``.

On completion of updating the documentation commit the corresponding `rst` files only. The compiled `html` files in the ``_build`` directory should be left ignored by Git.

Unconfirmed ideas for later (not a roadmap) live in :doc:`future_work`.
