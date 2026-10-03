.. _ssh_server:
.. highlight:: shell

===========
SSH servers
===========

``psynet debug ssh`` and ``psynet deploy ssh`` deploy to a Linux server that
you have :doc:`set up and registered </deploy/setting_up_a_server>`. This page
describes their addressing options, what they do on the server, and how to
work with a deployed app over SSH.

.. _ssh_server_addresses:

Server names and experiment addresses
-------------------------------------

``--server`` is a name registered with ``dallinger docker-ssh servers add`` or
``dallinger ec2 provision``, as listed by ``dallinger docker-ssh servers
list``. With one registered server it can be left out; with several, PsyNet
asks you to choose, or fails if the command is not run in an interactive
terminal.

``--dns-host`` sets the domain the experiment is served under. It defaults to
the ``--server`` name, so the experiment is served at
``https://<app>.<server>``. Pass it:

- if the server is registered by IP address. ``--server`` is then the IP
  address and ``--dns-host`` the public name, and leaving ``--dns-host`` out
  is an error:

  .. code:: bash

      psynet deploy ssh --app my-study --server 121.101.152.23 --dns-host my-server.example.org

- to use `nip.io <https://nip.io>`_ instead of a domain of your own.
  ``--dns-host nip.io`` serves the experiment at
  ``https://my-study.121.101.152.23.nip.io``. Some browsers warn participants
  about such names, and HTTPS certificates for nip.io names are sometimes
  unavailable because of rate limits.

Before deploying, Dallinger checks that ``<app>.<dns-host>`` resolves to the
server's IP address and stops with a ``DNS resolution error`` otherwise. A
wildcard record (``*.my-server.example.org``) covers every app name; with a
fixed list of records, ``--app`` must be one of them.

``--app`` may contain only lowercase letters, digits and hyphens, and must not
already be in use on the server. Without ``--app``, the experiment is served at
the ``--dns-host`` name itself rather than a subdomain, and its logs at
``https://<dns-host>/logs``. Such a deployment needs a server with no other
apps: Dallinger offers to destroy any it finds first.

.. _ssh_server_launch_info:

Launch information
------------------

At the end of a deployment, the command prints the log command, the Dozzle
address and the dashboard link with its credentials:

.. code:: text

    You can now log in to the console at
    https://admin:XXX@my-study.my-server.example.org/dashboard
    (user = admin, password = XXX)

PsyNet also saves the credentials in
``~/psynet-data/launch-data/<deployment-id>/launch-info.json``, where the
deployment ID has the form ``<label>__mode=<mode>__launch=<timestamp>``.

What a deployment does
----------------------

1. PsyNet runs its pre-deployment checks and prepares the experiment files
   from ``deploy.toml``.
2. Dallinger adds ``server_pem`` to your SSH agent and builds the Docker image
   with the server's Docker daemon, over SSH. The image stays on the server.
3. It writes the shared ``docker-compose.yml`` and ``Caddyfile`` to
   ``~/dallinger`` and starts the shared services.
4. It creates the app's database and database user, writes
   ``~/dallinger/<app>/docker-compose.yml``, starts the app's containers and
   initializes the database.
5. It adds the app's address to Caddy and calls the experiment's ``/launch``
   route, which opens recruitment.

Experiment containers run as the SSH user rather than root. Deploy chowns
``~/psynet-data/assets`` (and other writable ``docker_volumes`` bind mounts
under the home directory) so files left as root by older deploys stay
writable, retrying with a root Alpine container if needed.
``psynet export ssh`` reaches a deployment at the public origin recorded in
its deployment manifest.

To deploy with an unreleased Dallinger checkout, bake it into the image::

    psynet deploy ssh --app your-app-name --use-local-dallinger

PYTHONPATH is not enough: the image still pip-installs the Dallinger version
pinned in ``pyproject.toml``. ``--use-local-dallinger`` builds a wheel from
the editable checkout (or ``DALLINGER_SOURCE``), and the image build installs
it after ``COPY .``.

Services
^^^^^^^^

Each app runs these Docker Compose services:

- ``web``, which serves HTTP requests;
- ``worker_1`` to ``worker_N``, which process background tasks, one for each
  of ``num_dynos_worker``;
- ``clock``, which runs scheduled tasks;
- ``redis``, which holds the app's cache and task queue;
- ``pgbouncer``, which pools the app's database connections.

All apps share these services, defined in ``~/dallinger/docker-compose.yml``:

- ``postgresql``, which holds one database for each app;
- ``httpserver``, a `Caddy <https://caddyserver.com/>`_ server that routes
  each address to its app and obtains HTTPS certificates;
- ``dozzle``, the log viewer at ``https://logs.<dns-host>``.

Every service has the restart policy ``unless-stopped``, so Docker restarts
the apps when the server reboots.

Files on the server
^^^^^^^^^^^^^^^^^^^

``~/dallinger/``
   The shared ``docker-compose.yml``, ``Caddyfile`` and Dozzle login
   (``dozzle-users.yml``).
``~/dallinger/caddy.d/<app>``
   The app's Caddy configuration.
``~/dallinger/<app>/docker-compose.yml``
   The app's services and configuration.
``~/dallinger-data/<app>/``
   Files the app stores on the server, mounted in its containers at
   ``/var/lib/dallinger``.

``psynet destroy ssh`` stops the app's containers and removes
``~/dallinger/<app>/``, its Caddy configuration, and its image if no other app
uses it. The app's database stays in PostgreSQL until an app with the same
name is deployed, which replaces it.

.. _ssh_server_working_over_ssh:

Working with an app over SSH
----------------------------

Log in to the server with the key from ``server_pem`` and go to the app's
folder:

.. code:: bash

    ssh -i ~/.ssh/my-server.pem ubuntu@my-server.example.org
    cd ~/dallinger/my-study

If the folder doesn't exist, the deployment failed before it reached the
server. In the folder:

.. code:: bash

    docker compose logs          # logs of all the app's services
    docker compose logs -f web   # follow the web service's log
    docker compose exec web /bin/bash   # open a shell in the web container
    docker compose restart web   # restart one service

``docker ps`` lists the running containers of every app on the server. The
deployment command prints a one-line version of the log command that you
can run on your computer.

Connecting to the database
--------------------------

The PostgreSQL server starts with the first deployment. To open ``psql`` on
the server:

.. code:: bash

    docker compose -f ~/dallinger/docker-compose.yml exec postgresql psql -U dallinger

The database of each app has the app's name.

To connect a desktop client such as `Postico <https://eggerapps.at/postico2/>`_
through an SSH tunnel, first look up the database container's internal IP
address on the server:

.. code:: bash

    docker inspect \
        -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dallinger-postgresql-1

Then create a connection with these settings:

- Host: the IP address from ``docker inspect``
- Port: 5432
- User: ``dallinger``
- Password: ``dallinger``
- SSH tunnel: on, with the server's name or IP address as the SSH host, your
  username on the server, and the private key from ``server_pem``

Too many database connections
-----------------------------

Many apps on one server can use up PostgreSQL's connections, which are
limited to 100 by default. Apps then fail with:

.. code:: text

    psycopg2.OperationalError: FATAL:  remaining connection slots are reserved for non-replication superuser connections

To count the open connections, open ``psql`` as above and run:

.. code:: sql

    select datname as database_name, count(*)
    from pg_stat_activity
    group by datname;

Restarting an app's ``web``, ``worker_1`` and ``clock`` services with
``docker compose restart`` closes its connections. Restarts have occasionally
been followed by SQLAlchemy errors, so restart only when needed and check
that the app still works afterwards.

.. _docker_registry:

Docker registries
-----------------

``psynet debug ssh`` and ``psynet deploy ssh`` never push the image, so they
need no registry. A registry is needed only to deploy a prebuilt image named
by ``docker_image_name``, or to push images with Dallinger's ``dallinger
docker-ssh deploy --push-build`` or ``--local_build``. For pushing,
``docker_image_base_name`` must name a registry you can push to. The server
must be able to pull from the registry: run the same ``docker login`` on the
server as on your computer.

Docker Hub
   Create an account on `Docker Hub <https://hub.docker.com/>`_, sign in with
   ``docker login``, and set
   ``docker_image_base_name = docker.io/<username>/<image-name>``.

GitLab container registry
   Each GitLab project has a registry, which suits a team that shares
   images. Create a project such as ``experiment-images`` in the team's
   group, give everyone who deploys the Developer role or higher, and set
   ``docker_image_base_name =
   registry.gitlab.com/<group>/<project>/experiment-images`` (on a
   self-hosted GitLab, use its registry hostname). Sign in with:

   .. code:: bash

       docker login registry.gitlab.com -u your-username

   If you sign in to GitLab through another service, such as GitHub, Google
   or your institution, enter a
   `personal access token <https://gitlab.com/-/user_settings/personal_access_tokens>`_
   as the password.

Docker may warn that it stores the password unencrypted in
``~/.docker/config.json``; this works without a credential helper.
