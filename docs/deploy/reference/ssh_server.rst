.. _ssh_server:
.. highlight:: shell

===========
SSH servers
===========

PsyNet deploys experiments over SSH with ``psynet debug ssh`` and ``psynet
deploy ssh`` to a Linux server that you have
:doc:`set up and registered </deploy/setting_up_a_server>`.

Server size
^^^^^^^^^^^

As a very approximate rule of thumb, allow 5 GB of RAM for each experiment
that the server hosts at the same time.

Servers that only accept passwords
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Dallinger needs passwordless SSH access. If you normally log in to the server
with a password, generate a key on your local machine if you don't have one:

.. code:: bash

    ssh-keygen

Then upload it to the server, replacing the username and address as
appropriate:

.. code:: bash

    ssh-copy-id your-username@your-server.example.org

Check that you can now log in without a password:

.. code:: bash

    ssh your-username@your-server.example.org

Set ``server_pem`` to the private key (for example ``~/.ssh/id_ed25519``)
before registering the server.

Setting up a Docker registry (optional)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A Docker registry is needed only if you push your images, for example with Dallinger's ``dallinger docker-ssh
deploy --push-build`` or ``--local_build`` options. In that case
``docker_image_base_name`` must point to a registry you can push to.

Personal Docker registry on docker.io
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Create an account on `docker.io <https://www.docker.com/>`_.
- Install the Docker Desktop app and sign in.
- Set ``docker_image_base_name`` in ``config.txt`` for one experiment, or in
  ``~/.dallingerconfig`` for all of them:

  .. code:: ini

      docker_image_base_name = docker.io/<docker_io_username>/<name_of_your_image>

Group Docker registry on GitLab
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A group registry keeps a team's images in one place. GitLab provides a
container registry for each project, on gitlab.com or on a self-hosted
instance.

1. Create a GitLab project to hold the images, for example
   ``experiment-images``, inside a GitLab group.
2. Give everyone who deploys permission to push to the project's container
   registry, for example by adding the group as a project member with the
   Developer role or higher.
3. Log in to the registry from your computer:

   .. code:: bash

       docker login registry.gitlab.com

   On a self-hosted GitLab instance, use its registry hostname instead, for
   example ``registry.gitlab.example.org``.

4. Point ``docker_image_base_name`` in ``~/.dallingerconfig`` at the project:

   .. code:: ini

       docker_image_base_name = registry.gitlab.com/<group>/<project>/experiment-images

5. Open an SSH session on the server and run the same ``docker login``
   command there, so that the server can pull the images:

   .. code:: bash

       ssh your-username@your-server.example.org

If you cannot log in with your password on the command line (for example
with federated authentication), create a
`personal access token <https://gitlab.com/-/user_settings/personal_access_tokens>`_
and log in with your username, entering the token when prompted for a
password:

.. code:: bash

    docker login registry.gitlab.com -u your-username

.. note::

    Docker may warn that your password will be stored unencrypted in
    ``~/.docker/config.json`` and suggest a credential helper. You can usually
    continue without one.

.. note::

    If you created your GitLab account through an external service (for
    example GitHub or Google), you may need to set a GitLab password first.
    Make sure that you can log in to GitLab in the browser with only your
    email address; you may need to disconnect the external account (User
    Settings > Account) and reset your password.

Deploying experiments via SSH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You deploy experiments using the ``psynet deploy`` command:

.. code:: bash

    psynet deploy ssh --app your-app-name --server your-server.example.org

``--server`` chooses which server, registered with
``dallinger docker-ssh servers add`` (or ``dallinger ec2 provision``), to deploy
to. You can leave it out if you have registered only one server; with several,
PsyNet asks you to choose. For a server created with ``dallinger ec2
provision``, pass the ``--dns-host`` name. The experiment is served at a subdomain of the
server's name, here ``your-app-name.your-server.example.org``.

You only need ``--dns-host`` if you registered the server by IP address, or to
serve the experiment under a different domain.

If the server was registered by IP, pass both flags. ``--server`` is the
IP as stored by ``dallinger docker-ssh servers add``; ``--dns-host`` is
the public name:

.. code:: bash

    psynet deploy ssh --app your-app-name --server 121.101.152.23 --dns-host your-server.example.org

To use nip.io instead of a real domain, pass ``--dns-host nip.io``. The
experiment URL then looks like
``https://your-app-name.121.101.152.23.nip.io``. Omitting ``--dns-host``
on an IP-registered server is an error; PsyNet does not invent a nip.io
name for you.

Set up DNS so that each app name is a subdomain. A wildcard record such as
``*.your-server.example.org`` covers every app; a fixed list of names
means ``--app`` must be one of those names.

.. note::

    Do not use an underscore character (``_``) in ``your-app-name``. This can cause an
    error during deployment. The app name will be visible to participants, since it's
    used in the experiment URL, so make it meaningful without revealing too much about
    the experiment to participants.

When the experiment is successfully deployed, the terminal prints the dashboard URL
and login credentials, similar to this:

.. code:: text

    You can now log in to the console at
    https://admin:XXX@your-app-name.your-server.example.org/dashboard
    (user = admin, password = XXX)

PsyNet also saves the credentials in ``launch-info.json`` under
``~/psynet-data/launch-data/<deployment-id>/``, where the deployment ID
has the form ``<label>__mode=live__launch=<timestamp>``.
Save the dashboard link so that you can monitor the experiment while it collects data.
See :doc:`Deployment monitor </deploy/reference/deployment_monitor>` for details on what the
dashboard shows and how to interpret it.

Under the hood, the deployment command works as follows:

- Run any preliminary steps, e.g. uploading assets to the remote server
- Build the Docker image on the remote server (using the remote Docker daemon over SSH),
  packaging up all local code and dependencies
- Instruct the remote server to spin up the Docker app
- Instruct the remote server to launch the experiment

This command can go wrong at several points. The parts that happen on the local
machine are usually easiest to debug. When things go wrong on the remote server,
check the logs in the server's log viewer (Dozzle) at
``https://logs.<dns-host>``, where ``<dns-host>`` is the DNS name the
experiment is served under.
Often you will see the real error message in the `web` instance.

In some cases you may need to connect to the server via a separate SSH terminal to work out what's going on.
To connect to the server, run this in a separate terminal:

.. code:: bash

    ssh your-username@your-server.example.org

Navigate to the experiment's folder:

.. code:: bash

    cd ~/dallinger/your-app-name

If this folder doesn't exist yet, your command probably failed before it got
to the remote server.

This gives you another way to view the Docker logs for the web instance:

.. code:: bash

    docker compose logs

Sometimes it is useful to execute code on this remote Docker instance to work out
what happened. You can do this as follows:

.. code:: bash

    docker compose exec web /bin/bash

Under the hood
^^^^^^^^^^^^^^

It's worth knowing a few things about what's happening under the hood here so that you
are better positioned to debug things when they go wrong.

The SSH server works using Docker. Docker is a containerization service that virtualizes
entire operating systems and installed dependencies. This isolation is very helpful for ensuring
application portability.

When we work with Docker, we begin by creating a Docker *image*. A docker image is a snapshot
of an operating system in a particular status. The operating system we use here is Linux.
If you are familiar with the terminal in MacOS, then you will find Linux fairly intuitive.

Docker images are defined by writing Dockerfiles. Your experiment directory contains such a file,
it will be named ``Dockerfile``. Have a read through one such file to get a picture of how
the Docker image ends up being defined.

When we run an app we create one or more containers based on Dockerfiles. Containers are virtual
computers that are initialized according the snapshot provided in the Docker image.
You can run many containers on the same computer, but of course they all consume their own
computational resources.

The SSH server uses a tool called *docker compose* to orchestrate multiple containers for the
same app. Each PsyNet experiment contains the following services:

- ``web`` - serves HTTP requests
- ``worker_1``, ``worker_2``, ... - process asynchronous tasks (one per worker, set by ``num_dynos_worker``)
- ``clock`` - schedules tasks
- ``redis`` - stores variable values
- ``pgbouncer`` - pools the experiment's database connections

The SSH server additionally provides further services which are shared across all experiments:

- ``postgresql`` - hosts the experiment databases
- ``httpserver`` - a Caddy server that redirects HTTP requests to the appropriate experiment app. See
  `Caddy server <https://caddyserver.com/>`_ for more details.
- ``dozzle`` - serves the log viewer at ``https://logs.<dns-host>``

When you deploy an experiment to the SSH server, a folder is created in the location
``~/dallinger/your-app-name`` which contains a Docker compose configuration called
``docker-compose.yml``. You can inspect this configuration file to learn about how the app
is defined. When you SSH to this server, you can interact with this folder to
gain entry to your application. For example, you can run the following code to gain SSH access
to the web process of your app:

.. code:: bash

    cd ~/dallinger/your-app-name
    docker compose exec web /bin/bash

Within the same directory, you can run the following command to see live logs from your app:

.. code:: bash

    docker compose logs

You can run the following command to view the status of all Docker containers currently running on the server,
including containers from other apps:

.. code:: bash

    docker ps

Exporting the data and removing the app are covered in
:doc:`/deploy/running_a_study`.

Connecting to the database via SSH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is possible to connect to the remote server's PostgreSQL database via SSH.
This requires a one-time setup where you connect your local database client to the remote server.
We know that this is straightforward using Postico, a free database client for MacOS that we
recommend for use with PsyNet.

.. note::

    You can only connect to the database once you have deployed at least one experiment to the server,
    thereby initializing the PostgreSQL instance.

Before you can connect to the database, you need to find what internal IP address the database is running on.
To do this, SSH to the server and run the following command:

.. code:: bash

    docker inspect \
        -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dallinger-postgresql-1

Copy and paste the IP address that is returned.

Now, within Postico (or your alternative client), you should select the option to create a new connection,
and then fill in the following details:

- Host: the IP address you just copied
- Port: 5432
- User: dallinger
- Password: dallinger
- Tick 'Connect via SSH tunnel'
- SSH Host: the (external) IP address of your server, or its domain name
- SSH User: your username on the server
- Private key: the path to your private key (e.g. ``~/.ssh/id_rsa``)

You should now be able to connect to the PostgreSQL instance on the remote server.
This should contain multiple databases, one for each experiment you have deployed.

Known issues
^^^^^^^^^^^^

When many apps are deployed on the same server it is possible that certain apps
eat up too many database connections. This can manifest as an error like this:

.. code:: bash

    psycopg2.OperationalError: FATAL:  remaining connection slots are reserved for non-replication superuser connections

To check the current connections to the database,
run this on the remote server:

.. code:: bash

    cd ~/dallinger
    docker compose exec postgresql /bin/bash
    psql -U dallinger

    select pid as process_id,
       usename as username,
       datname as database_name,
       client_addr as client_address,
       application_name,
       backend_start,
       state,
       state_change
    from pg_stat_activity;

This will print a table of database connections. The number of rows is the number of database
connections. The limit is by default 100; if you are close to 100, then you are close to trouble.

Normally you can (temporarily) resolve problems with the number of connections by restarting certain
processes in an experiment. Restarting is fast and should not significantly impact on user experiences.
To restart processes for a given app, run the following:

.. code:: bash

    cd ~/dallinger/your-app-name
    docker compose restart web
    docker compose restart worker_1
    docker compose restart clock


.. warning::

    Sometimes we see SQLAlchemy errors as a result of running related commands, we're not entirely
    sure when/why this happens. For now it's worth avoiding restarting processes unless absolutely
    necessary. It's good to test that your app still works after doing this.
