.. _develop_troubleshooting:
.. highlight:: shell

=================================
Troubleshooting local development
=================================


.. _develop_troubleshooting_docker_space:

Docker no space left on device
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Suppose you see an error message like this when trying to run an experiment using Docker:

.. code:: bash

    ERROR: failed to solve: failed to copy: write /var/lib/docker/buildkit/content/ingest/ae8153b11f4d4f00d8b937b5de83ad657bae8a815251f89f9476de4147382577/data: no space left on device

This means too many old Docker images have accumulated on your system. This can be fixed by running the following command:

.. code:: bash

    docker system prune

If the error is on a remote SSH server rather than your laptop, also prune volumes and see
:ref:`Troubleshooting deployments <deploy_troubleshooting>`.

Docker connection errors
^^^^^^^^^^^^^^^^^^^^^^^^

.. code:: text

   docker.errors.DockerException: Error while fetching server API version:
   ('Connection aborted.', ConnectionRefusedError(61, 'Connection refused'))

The Docker daemon on your computer is not running; start Docker Desktop.

.. code:: text

   docker.errors.DockerException: Error while fetching server API
   version: ('Connection aborted.', PermissionError(13, 'Permission denied'))

Your user cannot access the Docker socket. On Linux, add your user to the
``docker`` group and log in again; otherwise, change the socket's
permissions.

Port 5000 is already in use
^^^^^^^^^^^^^^^^^^^^^^^^^^^

On macOS, turn off AirPlay Receiver (**System Settings > General > AirDrop &
Handoff**), which uses port 5000. Otherwise, stop any other experiment running
in another terminal or IDE window.

Database connection refused
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Suppose you see an error message like this:

.. code:: bash

    connection to server at "localhost" (::1), port 5432 failed: Connection refused
        Is the server running on that host and accepting TCP/IP connections?

PostgreSQL isn't running. If you use the Docker services that
:doc:`/install` sets up, check and start them from the experiment directory:

.. code:: bash

    psynet services check
    psynet services ensure

The rest of this section applies only to a PostgreSQL installed with Homebrew
on a Mac. Check the status of your database by running this command:

.. code:: bash

    brew services

If you don't see a line with ``postgresql``, PostgreSQL isn't installed with
Homebrew; use the Docker services above instead.

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

Heroku CLI not responding (local tests)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``psynet test local`` and ``psynet performance-test local`` start the
experiment with the Heroku CLI's ``heroku local`` command, so a broken Heroku
CLI installation can stop local tests from starting.


If the Heroku CLI doesn't respond, uninstall and reinstall it, then turn on its
debug output to see what goes wrong.

.. code-block:: bash

    brew uninstall heroku
    rm -rf ~/.local/share/heroku ~/Library/Caches/heroku

.. code-block:: bash

    brew install heroku/brew/heroku

After uninstalling and reinstalling the CLI, try running your tests again.

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

