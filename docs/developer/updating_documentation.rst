.. _developer:
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

The command deletes ``docs/_build`` first by default. For faster local reruns, pass
``--no-clean``. Extra Sphinx flags can be passed with ``--sphinx-option``.

Link internal pages with Sphinx roles such as ``:doc:`` or ``:ref:``, not raw
``.html`` paths. The published HTML site can resolve a relative path such as
``../tutorials/setting_up_slack.html``, but linkcheck looks for that ``.html``
file next to the ``.rst`` source and reports it as broken.

The generated HTML from ``psynet dev docs make`` is written to
``docs/_build/html/index.html``.

On completion of updating the documentation commit the corresponding `rst` files only. The compiled `html` files in the ``_build`` directory should be left ignored by Git.

Unconfirmed ideas for later (not a roadmap) live in :doc:`future_work`.
