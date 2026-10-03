Running and debugging locally
=============================

Run the experiment in debug mode
--------------------------------

Start the local database and cache, then the experiment:

.. code-block:: bash

    psynet services ensure
    psynet debug local

``psynet services ensure`` offers to start PostgreSQL and Redis in Docker if
they aren't running. ``psynet debug local`` starts the same web, worker and
clock processes that a deployed experiment runs, which takes 10 to 15
seconds, then opens the dashboard and a participant session in your browser.
Press :kbd:`Ctrl+C` in the terminal to stop it.

When a script or a coding agent starts ``psynet debug local`` in a
background shell without a terminal, keep its standard input open, for
example ``tail -f /dev/null | psynet debug local``. Otherwise the server can
stop without a log message when standard input closes.

Most code changes, such as editing a page, adding timeline elements or
changing code block logic, take effect when you save the file and refresh the
page. Changes to assets in the timeline need a restart.

To run the experiment inside its Docker image instead, as it runs when
deployed, use ``psynet debug local --docker``.

Set a breakpoint
----------------

PsyNet runs experiment code in subprocesses, which ordinary IDE breakpoints
don't reach. Use :func:`psynet.debugger` instead:

.. autofunction:: psynet.debugger

``psynet setup`` creates the ``.vscode/launch.json`` file that this function
needs.

If ``psynet.debugger`` doesn't work in your setup, use
`rpdb <https://pypi.org/project/rpdb/>`_, a remote version of Python's
`pdb debugger <https://docs.python.org/3/library/pdb.html#debugger-commands>`_.
It is installed with PsyNet. To set a breakpoint, add:

.. code-block:: python

    import rpdb; rpdb.set_trace()

When the code reaches the breakpoint, connect to it from another terminal:

.. code-block:: bash

    nc 127.0.0.1 4444

Track down an error
-------------------

Errors appear in the terminal running ``psynet debug local``, with a
traceback showing where they happened. If the traceback ends in PsyNet code,
read that part of the PsyNet source to see what it expected. A breakpoint
just before the failing line shows the values of the local variables.

If the cause is still unclear, simplify the experiment until the error
disappears, for example by commenting out parts of the timeline. Share the
smallest version that still fails when you ask for help.

Inspect the experiment in the dashboard
---------------------------------------

The dashboard (see :ref:`experiment_dashboard`) shows the current state of
the experiment. Its **Database** tab lists the objects in the database, and
**Monitor > Monitoring** shows the experiment's networks.

Query the database directly
---------------------------

The local experiment stores its data in PostgreSQL. Connect with:

.. code-block:: bash

    psql -h localhost -U dallinger -d dallinger

The password is ``dallinger``. The main tables are ``participant``,
``trial``, ``response`` (page answers), ``node`` and ``network`` (trial maker
nodes and chains) and ``asset``; ``\dt`` lists them all. For example:

.. code-block:: sql

    -- Recent participants
    SELECT id, worker_id, status, creation_time FROM participant
    ORDER BY creation_time DESC LIMIT 5;
    -- Latest answers
    SELECT id, answer FROM response ORDER BY id DESC LIMIT 10;
