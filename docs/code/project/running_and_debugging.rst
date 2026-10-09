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

.. _running_several_local_experiments:

Run several experiments at once
-------------------------------

``psynet test local`` runs in its own database, Redis server and port
automatically, so you can run tests while ``psynet debug local`` is serving
another experiment, and run several test sessions at once.

By default every ``psynet debug local`` uses port 5000, the ``dallinger``
PostgreSQL database, the Redis server on port 6379 and the
``/tmp/dallinger_develop`` folder, so only one can run at a time. To run
another one alongside it, for example when several coding agents test
different experiments on one machine, add ``--isolated``:

.. code-block:: bash

    psynet debug local --isolated

It picks a free port (5100 or above) and uses a database and a Redis server
of its own, which it starts and stops with the server. It prints the port, and
the ``export`` line that points other local commands, such as
``psynet export local``, at it; with ``--no-browsers`` it repeats that line
under the dashboard credentials. Local commands run in the served directory
refuse to run when they would read a different database from the server. The
database stays after the server stops, until the next ``--isolated`` server
on the same port resets it, which that server mentions. Its Redis server
doesn't stay, so after the server stops, export only ``DATABASE_URL``. If the
launcher is killed outright, Linux still stops the server and its Redis
server.

Two debug servers can't share an experiment directory, because each replaces
the generated files the other serves. ``--isolated`` refuses to start where
another ``psynet debug`` is already serving; plain ``psynet debug local``
doesn't check, so give each server its own copy, such as a git worktree.

To choose the settings yourself instead, give the second terminal its own
database, Redis server, port and development folder:

.. code-block:: bash

    PGPASSWORD=dallinger createdb -h localhost -U dallinger dallinger_2
    redis-server --port 6381 --bind 127.0.0.1 --dir "$(mktemp -d)" --save "" --daemonize yes

    export DATABASE_URL=postgresql://dallinger:dallinger@localhost/dallinger_2
    export REDIS_URL=redis://localhost:6381
    export base_port=5010
    export dallinger_develop_directory=/tmp/dallinger_develop_2

``psynet debug local`` in that terminal then serves on port 5010 and leaves
the other experiment's processes and browsers alone.
Use a separate Redis server rather than another database number on the same
server: Redis delivers PsyNet's live notifications (for example waking a
participant who waits on a page) to every database on a server, so two
experiments sharing one would wake each other's participants.

Two runs in the same experiment directory still conflict, because each
creates and removes generated files there. Tests wait for each other
automatically and refuse to start while ``psynet debug`` serves the same
directory; to debug and test at once, or to debug twice, use a separate copy
(such as a git worktree) of the experiment.

``psynet services list`` shows which ports, databases and Redis servers the
sessions running on your machine already use.

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

The password is ``dallinger``. A server started with ``--isolated`` uses the
database it prints at startup, such as ``dallinger_debug_5100``; pass that name
to ``-d`` instead. The main tables are ``participant``,
``trial``, ``response`` (page answers), ``node`` and ``network`` (trial maker
nodes and chains) and ``asset``; ``\dt`` lists them all. For example:

.. code-block:: sql

    -- Recent participants
    SELECT id, worker_id, status, creation_time FROM participant
    ORDER BY creation_time DESC LIMIT 5;
    -- Latest answers
    SELECT id, answer FROM response ORDER BY id DESC LIMIT 10;
