=========
PsyNet 15
=========

PsyNet 15 is in development. This page collects its highlights as they land.
The `changelog <https://gitlab.com/PsyNetDev/PsyNet/-/blob/master/CHANGELOG.md>`_
lists every change.

Page configuration
------------------

**``js_vars`` is now ``page_config``.** A page's JavaScript gets three kinds
of data, each with its own name:

- ``page_config``, read as ``psynet.pageConfig``, configures the page, such as
  a task's timings or a slider's range. It is the same for every trial the
  page shows.
- ``contents``, read as ``psynet.page.contents``, holds what the page shows,
  such as a trial's stimulus, and can change from trial to trial; on a page
  that shows several trials, each ``update()`` receives it (see
  :doc:`/code/trials/keeping_a_task_on_one_page`).
- PsyNet's own state for the page, such as its page UUID, is internal and no
  longer mixed into the page's configuration.

Rename these in your experiment:

.. list-table::
   :header-rows: 1

   * - Before
     - Now
   * - ``Page(js_vars=...)``, ``ModularPage(js_vars=...)``
     - ``page_config=...``
   * - ``get_js_vars()``
     - ``get_page_config()``
   * - ``get_participant_js_vars(experiment, participant)``
     - ``get_participant_page_config(experiment, participant)``
   * - ``psynet.var``
     - ``psynet.pageConfig``
   * - ``vars`` in a page module's ``activate()``
     - ``config``

The old names keep working until PsyNet 16, with a ``DeprecationWarning`` in
Python and a console warning when ``psynet.var`` reads one of PsyNet's
internal values. See :doc:`/code/pages/custom_front_ends`.

While renaming, check what you pass: a value that differs from trial to
trial, such as a stimulus or a condition's parameter, belongs in the page's
``contents``, and one that differs between rounds of a live game belongs in
the game's settings and views. The page's configuration is for what stays
the same.
