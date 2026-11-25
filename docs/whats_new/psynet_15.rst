=========
PsyNet 15
=========

PsyNet 15 is in development. This page collects its highlights as they land.
The `changelog <https://gitlab.com/PsyNetDev/PsyNet/-/blob/master/CHANGELOG.md>`_
lists every change.

Pages without waiting for the server
------------------------------------

**The next page appears as soon as the participant answers**, where PsyNet
can tell what it is, and the answer is sent in the background:

- A page that comes straight after another page in the timeline, with no
  code in between, is rendered in advance. Nothing to change; opt a page out
  with ``render_in_advance=False`` if it shows something the previous answer
  changes (see :ref:`showing_the_next_page_without_waiting`).
- Such pages get a **Back** button when the earlier page collects no answer,
  as in a run of instruction pages. Hide it with ``show_back_button=False``
  (see :ref:`going_back_to_the_previous_page`).
- ``StaticTrialMaker(prepare_trials_in_advance=True)`` prepares a
  participant's trials in order, shows the next trial's page as soon as the
  participant answers and downloads the next trials' files early (see
  :ref:`showing_the_next_trials_without_waiting`).
- The new :class:`~psynet.page.JSPage` is a page written as your own HTML
  and one JavaScript module. Consecutive trials share one page, which suits
  fast tasks such as reaction time tasks (see
  :doc:`/code/trials/keeping_a_task_on_one_page`).

Code that relied on the old behaviour may notice that page UUIDs now follow
from the participant and the page rather than being random, and that the
undocumented ``psynet.nextPagePending`` is now
``psynet.pageState.submitting``.

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
   * - ``psynet.var``
     - ``psynet.pageConfig``
   * - ``vars`` in a page module's ``activate()``
     - ``config``

The old names keep working until PsyNet 16, with a warning in Python that
points at the line to change, and a console warning when ``psynet.var``
reads one of PsyNet's internal values. See :doc:`/code/pages/custom_front_ends`.

While renaming, check what you pass: a value that differs from trial to
trial, such as a stimulus or a condition's parameter, belongs in the page's
``contents``, and one that differs between rounds of a live game belongs in
the game's settings and views. The page's configuration is for what stays
the same.
