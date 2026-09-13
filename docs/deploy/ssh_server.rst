.. _ssh_server:
.. highlight:: shell

===========
SSH servers
===========

The recommended approach for hosting your own PsyNet experiments is to
set up your own remote server accessed via SSH. We will refer to such
servers as 'SSH servers'.

Setting up the remote server
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are several ways to set up your own remote server.
One way is to rent one via Amazon Web Services (see :ref:`tutorial <aws_server_setup>`).
Other comparable recommended companies include Hetzner and Contabo.
As a very approximate rule of thumb, we recommend 5 GB of RAM for each
simultaneous experiment you think you will need to host.

Once you've set up your remote server, you need to make sure that your local computer
has passwordless SSH access to the remote server.
If you have a key pair for the server, you probably need to add it to your SSH agent
with code like the following:

.. code:: bash

    chmod 600 path/to/your/key.pem
    ssh-add path/to/your/key.pem

If you normally need a password to access the instance, you'll need to
upload your local machine's SSH key to the remote instance. If you don't have
an SSH key already, generate one on your local machine:

.. code:: bash

    ssh-keygen

Then upload it to the remote instance by running a command in the following form,
replacing the credentials and server address as appropriate:

.. code:: bash

    ssh-copy-id yourusername@your-server.ac.uk

Verify that you can login passwordless by running the following:

.. code:: bash

    ssh your-username@your-server.ac.uk

If this works, you're ready to register the remote server within PsyNet/Dallinger.
Run the following:

.. code:: bash

    dallinger docker-ssh servers add --user your-username --host your-server.ac.uk


Setting up your Docker registry
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The Docker registry will host your Docker images. There are multiple platforms you can use to host your Docker images. Here we will cover docker.io and GitLab.
We will cover three ways to setup a Docker registry:
- personal Docker registry on docker.io
- group Docker registry on GitLab
- self-hosted Docker registry on GitLab

Personal Docker registry on docker.io
=====================================

- Go to `docker.io <https://www.docker.com/>` and setup an account
- Download the Docker Desktop app and sign in
- Add the following line to your ``config.txt`` if you only want to use it for this experiment or in ``~/.dallingerconfig`` if you want to use it as your default registry:

    .. code:: bash

        docker_image_base_name = docker.io/<docker_io_username>/<name_of_your_image>



Group Docker registry on GitLab
===============================

Group Docker registries are a nice way to have all of your lab's Docker images under the same umbrella. 

There's two ways to set up a Docker registry:
- A hosted Docker registry
- A self-hosted Docker registry

We'll first go through the steps to setup a hosted Docker registry on Gitlab. First login to the GitLab docker registry:

.. code:: bash

    docker login registry.gitlab.com


The next step is to setup a public repository, e.g. a repository called "experiment-images" by the user "computational-audition". This means the particular user ("computational-audition") can now push to this registry. In the case of the lab, we suggest setting up a lab group where all users have "Maintainer" permissions. You can now add this group to your repository https://gitlab.com/<user>/<repo>/-/project_members (e.g., https://gitlab.com/computational-audition/experiment-images/-/project_members). Now each user in the lab group can push to the repository.

The last step is to add the registry to ``.dallingerconfig``. To do this, you need to edit your local
``~/.dallingerconfig`` file.

If you don't have such a file already, you can create it like this:

.. code:: bash

    touch ~/.dallingerconfig

You can then edit it on Mac like this:

.. code:: bash

    open ~/.dallingerconfig

or simply with a text editor via your GUI.

Place a line like the following in your ``~/.dallingerconfig``,
putting the link to your own image registry:

.. code:: bash

    docker_image_base_name = registry.gitlab.developers.cam.ac.uk/mus/cms/psynet-experiment-images



You can also host the registry yourself, e.g. under ``registry.gitlab.developers.cam.ac.uk``. The steps are similar to above, but you will need to change the URL if you are using a self-hosted registry. For example:

.. code:: bash

    docker login registry.gitlab.developers.cam.ac.uk

In some situations (e.g. federated authentication) you will not be able to login
to your account via the command-line in this way. Instead, you will have to create
a `personal access token via GitLab <https://gitlab.developers.cam.ac.uk/-/profile/personal_access_tokens>`_
and then login with a command like the following:

.. code:: bash

    docker login registry.gitlab.developers.cam.ac.uk -u your-username

You should then enter your access token when prompted.

.. note::

    If you see this error:

    .. code:: bash

        WARNING! Your password will be stored unencrypted in /home/pmch2/.docker/config.json.

        Configure a credential helper to remove this warning. See

        https://docs.docker.com/engine/reference/commandline/login/#credentials-store

    you can probably continue without worrying about it. We are still working out
    the best way to deal with Docker credential management in PsyNet/Dallinger.

.. note::

    You might not be able to login if you originally created your gitlab account via an external service (e.g. GitHub, Gmail).
    In that case, make sure, that you can login to GitLab in the browser, using only your email adress. 
    You might need to disconnect your external (e.g. GitHub) account from your GitLab account 
    (User Settings -> Account) and reset your password to do so.

You then need to do exactly the same `docker login` process but on your remote server.
To do this, you need to open an SSH terminal to your server, if you haven't already:

.. code:: bash

    ssh your-username@your-server.ac.uk

Then run the same `docker login` command that you ran previously.

Finally, you need to place a line like the following in your ``~/.dallingerconfig``,
putting the link to your own image registry:

.. code:: bash

    docker_image_base_name = registry.gitlab.developers.cam.ac.uk/mus/cms/psynet-experiment-images

That's it! You should be all set up now.

Deploying experiments via SSH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You deploy experiments using the ``psynet deploy command``:

.. code:: bash

    psynet deploy ssh --app your-app-name

By default, this will deploy your app to a hostname that looks like this:

https://your-app-name.121.101.152.23.nip.io

where ``121.101.152.23`` is the IP address of your web server.
If your server is set up with a DNS record, it is possible to use this instead as the URL.
For example, running this:

.. code:: bash

    psynet deploy ssh --app your-app-name --dns-host my-web-server.com

would make your app available at this link:

https://your-app-name.my-web-server.com

Note that your DNS record must already be set up to resolve the subdomain you want to use (e.g. ``your-app-name``)
to the IP address of the server.
This is a one-time job that should be performed when preparing the web server to deploy experiments.
You can either do this by setting up a subdomain wildcard (e.g. ``*.my-web-server.com``, or by deciding in advance
what experiment names to support, and then setting up the DNS to support those names
(e.g. ``psynet-01.my-web-server.com``, ``psynet-02.my-web-server.com``, etc.).

.. note::

    If your DNS record only supports particular subdomains then you have to choose your app name to match
    one of those subdomains. For example, when deploying through the web server of the Centre for Music and Science
    at Cambridge, only app names of the form ``psynet-01``, ``psynet-02``, ..., ``psynet-20`` are supported.

Under the hood, the deployment command works as follows:

- Run any preliminary steps, e.g. uploading assets to the remote server
- Build the Docker image, packaging up all local code and dependencies
- Push the Docker image to the remote server
- Instruct the remote server to pull the Docker image
- Instruct the remote server to spin up the Docker app
- Instruct the remote server to launch the experiment

This command can go wrong at several points. The parts that happen on the local
machine are usually easiest to debug. When things go wrong on the remote server,
you probably want to check the logs. You can do this by navigating to 
`logs.<dns-host>`, where you replace `dns-host` with the DNS host you specified in the deploy command.
(e.g. logs.musix.mus.cam.ac.uk).
Often you will see the real error message in the `web` instance.

In some cases you may need to connect to the server via a separate SSH terminal to work out what's going on.
To connect to the server, run this in a separate terminal:

.. code:: bash

    ssh your-username@your-server.ac.uk

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
same app. Each PsyNet experiment contains four distinct containers:

- ``web`` - serves HTTP requests
- ``worker`` - process asynchronous tasks
- ``clock`` - schedules tasks
- ``redis`` - stores variable values

The SSH server additionally provides two further containers which are shared across all experiments:

- ``postgresql`` - hosts the experiment databases
- ``caddy`` - redirects HTTP requests to the appropriate experiment app. See
  `Caddy server <https://caddyserver.com/>`_ for more details.

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

Once you are done with your experiment, you can export the data to your local computer using the following command,
but run it on your local computer, not via your SSH terminal.

.. code:: bash

    psynet export ssh --app your-app-name

For more information, see :doc:`Exporting </deploy/data>`.

You can then tear down your app via the following command, again run on your local computer:

.. code:: bash

    psynet destroy ssh --app your-app-name


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
    docker compose restart worker
    docker compose restart clock


.. warning::

    Sometimes we see SQLAlchemy errors as a result of running related commands, we're not entirely
    sure when/why this happens. For now it's worth avoiding restarting processes unless absolutely
    necessary. It's good to test that your app still works after doing this.
