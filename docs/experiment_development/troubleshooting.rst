.. _develop_troubleshooting:
.. highlight:: shell

===============
Troubleshooting
===============


Docker unauthorized
^^^^^^^^^^^^^^^^^^^

Suppose you see an error message like this when trying to run an experiment using Docker:

.. code:: bash

     => ERROR [internal] load metadata for registry.gitlab.com/psynetdev/psynet:v10.4.0
     => [auth] psynetdev/psynet:pull token for registry.gitlab.com
    ------
     > [internal] load metadata for registry.gitlab.com/psynetdev/psynet:v10.4.0:
    ------
    Dockerfile:1
    --------------------
       1 | >>> # syntax = docker/dockerfile:1.2
       2 |     #
       3 |     # Note - the syntax of this Dockerfile differs in several ways from the sample Dockerfile
    --------------------
    ERROR: failed to solve: failed to authorize: failed to fetch oauth token: unexpected status: 401 Unauthorized

This normally means you have out-of-date credentials in your Docker client. Try running the following:

.. code:: bash

    docker login registry.gitlab.com


Docker no space left on device
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Docker unauthorized
^^^^^^^^^^^^^^^^^^^

Suppose you see an error message like this when trying to run an experiment using Docker:

.. code:: bash

    ERROR: failed to solve: failed to copy: write /var/lib/docker/buildkit/content/ingest/ae8153b11f4d4f00d8b937b5de83ad657bae8a815251f89f9476de4147382577/data: no space left on device

This means too many old Docker images have accumulated on your system. This can be fixed by running the following command:

.. code:: bash

    docker system prune

Database connection refused
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Suppose you see an error message like this:

.. code:: bash

    connection to server at "localhost" (::1), port 5432 failed: Connection refused
        Is the server running on that host and accepting TCP/IP connections?

This means that your local Postgres database cannot be accessed.
This would normally only happen if you are not using PsyNet through Docker.

If you are on a Mac, you can check the status of your database by running this command:

.. code:: bash

    brew services

If you don't see a line with ``postgresql``, you have not installed PostgreSQL.
Follow the virtual environment installation instructions to do so.

If you do see a line with ``postgresql``, it probably has ``error`` written next to it.
You need to get access to the logs to debug this error.
To do so, look at the ``File`` column of the ``brew services`` output,
find the value corresponding to ``postgresql``. Print that file in your terminal using ``cat``,
for example:

.. code:: bash

    cat ~/Library/LaunchAgents/homebrew.mxcl.postgresql@14.plist

Look for a line like this:

.. code:: bash

    <key>StandardErrorPath</key>

The error log path is contained underneath it, between the ``<string>`` identifiers.
View the last few lines of that file in your terminal using ``tail``, for example:

.. code:: bash

    tail /usr/local/var/log/postgresql@14.log

Have a look at the error message.
One possible message is something like this:

.. code:: bash

    2023-04-25 16:53:51.224 BST [28527] FATAL:  lock file "postmaster.pid" already exists
    2023-04-25 16:53:51.224 BST [28527] HINT:  Is another postmaster (PID 716) running in data directory "/usr/local/var/postgresql@14"?

If you see this error message, try restarting your computer and trying again.

Another possible error message is this:

.. code:: bash

    Reason: tried: '/usr/local/opt/icu4c/lib/libicui18n.72.dylib' (no such file)

It has proved possible in the past to fix this problem by running the following:

.. code:: bash

    brew reinstall postgresql@14
    brew services restart postgresql@14

where ``postgresql@14`` should be replaced with the exact name for the Postgres service that you saw in ``brew services``.

If that doesn't work, try searching Google for help. If you find another solution,
please share your experience here.

.. _running_several_experiments:

Running several experiments at once
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default every local experiment uses the same PostgreSQL database, the same
Redis database, the same development directory and port 5000, so starting a
second experiment fails with "Another local experiment is using the same
database" or "Another local experiment server ... is running from the
development directory". To run two experiments side by side, give the second
one its own database, Redis database, development directory and port.
PostgreSQL and Redis can stay on their usual ports 5432 and 6379.

.. code:: bash

    # Once: create a second database (here inside the psynet services container)
    docker exec dallinger_postgres createdb -U dallinger second_experiment

    # In the second experiment's terminal
    export DATABASE_URL=postgresql://dallinger:dallinger@localhost/second_experiment
    export REDIS_URL=redis://localhost:6379/1
    psynet debug local

and set a different port and development directory in that experiment's
``config.txt`` (the directory path must not contain a period):

.. code:: ini

    [Server]
    base_port = 5001
    dallinger_develop_directory = /tmp/dallinger_develop_second

``psynet services check`` and ``psynet services ensure`` test the services at
``DATABASE_URL`` and ``REDIS_URL``. ``psynet services ensure`` only starts
Docker containers on the default localhost ports, and refuses to start one
when another PostgreSQL or Redis install already uses that port; in that case,
point ``DATABASE_URL`` or ``REDIS_URL`` at the existing install instead.


MISCONF Redis is configured to save RDB snapshots
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you you see an error beginning 'MISCONF Redis is configured to save RDB snapshots',
and you are using MacOS, then you may be able to fix your problem by running the following command:

.. code:: bash

    brew services restart redis


Postgres stops working after a Homebrew upgrade
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


If you find that Postgres stops working after upgrading via Homebrew,
you might need to delete your local Postgres files and try again.
This can be done as follows
(these instructions are from `Moncef Belyamani's tutorial <https://www.moncefbelyamani.com/how-to-upgrade-postgresql-with-homebrew/>`_):

.. code-block:: bash

   brew remove --force postgresql

Or if you had previously a versioned form of Postgres, for example Postgres 14:

.. code-block:: bash

   brew remove --force postgresql@14

Delete the Postgres folders:

.. code-block:: bash

   rm -rf /usr/local/var/postgres/
   rm -rf /usr/local/var/postgresql@14/

Or if you're on an Apple Silicon Mac:

.. code-block:: bash

   rm -rf /opt/homebrew/var/postgres
   rm -rf /opt/homebrew/var/postgresql@14

Finally you can reinstall Postgres:

.. code-block:: bash

   brew install postgresql@14
   brew services start postgresql@14

Heroku Startup Error / CLI not responding
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


If you're experiencing issues with Heroku CLI not responding or encountering errors, you can try uninstalling and reinstalling it first. After that, enable debugging environment variables to get more detailed logs and information about what might be going wrong. This can help you diagnose and resolve the problem more effectively.


If the CLI is not responding or you're experiencing issues, you can try uninstalling and reinstalling it.

.. code-block:: bash

    brew uninstall heroku
    rm -rf ~/.local/share/heroku ~/Library/Caches/heroku

.. code-block:: bash

    brew install heroku/brew/heroku

After uninstalling and reinstalling the CLI, try running the Heroku command again.

If the issue persists, open your terminal and set the following environment variables to enable debugging:

.. code-block:: bash

    export HEROKU_DEBUG=1
    export HEROKU_DEBUG_HEADERS=1
    export DEBUG=*

- **HEROKU_DEBUG=1**: Enables debug logging for the Heroku CLI.
- **HEROKU_DEBUG_HEADERS=1**: Enables debug logging for HTTP headers, useful for troubleshooting authentication or networking issues.
- **DEBUG=***: Enables debug logging for all modules used by the Heroku CLI.


To verify your CLI installation, use the ``heroku --version`` command:

.. code-block:: bash

    heroku --version

If the CLI is installed correctly, you should see output similar to:

.. code-block:: text

    heroku/7.0.0 (darwin-x64) node-v8.0.0

