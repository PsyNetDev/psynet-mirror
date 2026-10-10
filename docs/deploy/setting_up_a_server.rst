Setting up a server
===================

You set up a server once and then deploy any number of experiments to it.

Choosing a server
-----------------

A PsyNet server is a Linux machine (Ubuntu is recommended) that meets these
requirements:

- You can log in over SSH with a key file, without a password.
- The account you log in with can run Docker: either it is in the ``docker``
  group, or it has passwordless ``sudo`` so that Dallinger can install Docker
  and add it to the group when you register the server.
- Ports 80 and 443 are free and reachable from the internet.
- It has a DNS name, and every subdomain of that name resolves to the server
  as well (a wildcard record such as ``*.my-server.example.org``). Each
  experiment is served at a subdomain.

A pilot runs on a machine with 2 CPU cores and 8 GB of RAM, such as an AWS
``m7i.large`` instance. A live study usually needs at least 4 cores and 16 GB,
such as an ``m7i.xlarge``; to size the server for your study, see
:ref:`choosing_server_size`. Allow 5 GB of RAM for each experiment that runs
on the server at the same time.

The usual choices are:

- **An AWS EC2 instance provisioned by Dallinger.** One command creates the
  machine, its DNS records and its registration. You pay for the instance
  while it exists; at the time of writing (October 2026) an ``m7i.xlarge``
  costs around $0.23 an hour, so a five-hour study costs around $1.
- **A virtual machine from any cloud provider**, such as Hetzner, Contabo, or
  AWS configured by hand in the console.
- **A physical machine** run by you or your institution.

A server that Dallinger doesn't provision needs key-based SSH login and DNS
records before you register it; see
:doc:`/deploy/reference/manual_server_setup`.

.. lab-note::

   Your lab may already run a shared server or a shared AWS account. Ask your
   lab administrator which server to use before you set up a new one, and to
   confirm that:

   - you have access to the lab's GitLab group;
   - you can push to the lab's Docker registry, if the lab pushes images to
     one;
   - your SSH key is registered wherever the lab requires it, for example
     on GitLab or on the lab's servers;
   - you have received the lab's credential files (see below).

.. _choosing_server_size:

Choosing a server size
^^^^^^^^^^^^^^^^^^^^^^

How many participants a server can serve at the same time depends mostly on
its CPU. What matters is the number taking part at the same moment, not the
total: recruitment platforms can send many participants within minutes of a
study opening, so plan for that peak rather than for the average.

In one test, a simple rating experiment (ten static trials and one async
process) ran on a desktop server with 8 cores, 16 CPU threads and 32 GB of
RAM (AMD Ryzen 7 5800X). With 480 bots at once working at a realistic pace,
the 95th-percentile response time was about 100 ms, with no errors. The
experiment used about 7 of the 16 threads (5 for the web workers, 2 for the
database), so the server could probably take a few hundred more. Memory
was not the limit: the experiment used about 4 GB.

With Dallinger 12.4 and earlier, the database connection pool caps every
docker-ssh server at about 200 participants at a time, whatever its size: in
the same test, the response time rose to over 400 ms at 320 bots while most
of the CPU sat idle.

A cloud vCPU is one CPU thread, often on a slower core, and most experiments
do more work per page than this one, so as a starting point plan on 20 to 30
participants at a time per vCPU:

.. list-table::
   :header-rows: 1

   * - AWS instance
     - vCPUs
     - RAM
     - Participants at a time
     - Price per hour
   * - ``m7i.large``
     - 2
     - 8 GB
     - 40–60
     - $0.12
   * - ``m7i.xlarge``
     - 4
     - 16 GB
     - 80–120
     - $0.23
   * - ``m7i.2xlarge``
     - 8
     - 32 GB
     - 160–240
     - $0.47
   * - ``m7i.4xlarge``
     - 16
     - 64 GB
     - 320–480
     - $0.93

Prices are on-demand Linux prices in the London region (``eu-west-2``) in
October 2026; US regions are about 15% cheaper. See AWS's lists of
`instance types <https://aws.amazon.com/ec2/instance-types/>`_ and
`on-demand prices <https://aws.amazon.com/ec2/pricing/on-demand/>`_.
These figures are only a starting point. Before a large study, measure your
own experiment on the server you will use (see
:ref:`performance_testing_server`), and cap the number of participants at a
time with ``max_concurrent_participants``.

The server is a small part of a study's cost. 100 participants at once, paid
£9 an hour, cost about £900 an hour, while an ``m7i.4xlarge`` that can serve
several times as many costs under $1 an hour. A server that is too small
makes pages slow or fail for everyone taking part, which wastes their time
and your payments, so choose a size with room to spare. Remember to tear the
server down afterwards: a forgotten ``m7i.4xlarge`` costs about $22 a day.

Configuring your computer
-------------------------

Deployment settings that apply to all your experiments go in
``~/.dallingerconfig`` in your home directory. Create it if it does not exist:

.. code-block:: bash

    touch ~/.dallingerconfig

The file uses INI syntax. Every setting must be inside a section; the section
names (``[SSH]``, ``[Docker]`` and so on) are free to choose. Write comments
on their own lines, because a comment written after a value becomes part of
the value.

SSH key
^^^^^^^

Dallinger connects to the server with a single private key file, set as
``server_pem``. It uses only this key, even if your SSH client has others,
and adds it to your SSH agent while it builds images on the server, so an
``ssh-agent`` must be running. If none is, ``ssh-add -l`` reports that it
cannot connect to the agent; start one with ``eval "$(ssh-agent)"``. The key
might be your personal key (``~/.ssh/id_ed25519`` or ``~/.ssh/id_rsa``) or a
PEM file you received with the server; keep PEM files in ``~/.ssh`` and make
them readable only by you:

.. code-block:: bash

    chmod 600 ~/.ssh/my-server.pem

Then add the path to ``~/.dallingerconfig``:

.. code-block:: ini

    [SSH]
    server_pem = ~/.ssh/my-server.pem

Docker image name
^^^^^^^^^^^^^^^^^

PsyNet refuses to deploy over SSH unless ``docker_image_base_name`` is set.
``psynet debug ssh`` and ``psynet deploy ssh`` build the image on the server
and do not push it, so any name works and you do not need a Docker registry
account:

.. code-block:: ini

    [Docker]
    docker_image_base_name = psynet-experiments

A registry is needed only if you push images yourself; see
:ref:`docker_registry`.

Dashboard credentials and contact email
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each experiment's dashboard is protected by ``dashboard_user`` and
``dashboard_password``. If you leave the password out, a new random one is
generated for each deployment and printed at the end; ``dallinger ec2
provision`` requires both to be set. ``contact_email_on_error`` must be a
valid address: the server uses it to obtain HTTPS certificates from Let's
Encrypt, and participants see it on error pages.

.. code-block:: ini

    [Dashboard]
    dashboard_user = admin
    dashboard_password = choose-a-strong-password

    [Email]
    contact_email_on_error = you@example.org

.. lab-note::

   Your lab administrator may provide a ready-made ``.dallingerconfig`` and
   PEM key, for example in an encrypted archive in a private credentials
   repository. Place ``.dallingerconfig`` in your home directory and the PEM
   file in ``~/.ssh``, run ``chmod 600`` on the PEM file, and check that
   ``server_pem`` points to it. The lab's file may already set
   ``docker_image_base_name``, the AWS settings and a shared security group.

Registering the server
----------------------

.. tab-set::
   :sync-group: server

   .. tab-item:: Existing server
      :sync: existing

      Check that you can log in with the key from ``server_pem`` (replace
      ``ubuntu`` with your username on the server):

      .. code-block:: bash

          ssh -i ~/.ssh/my-server.pem ubuntu@my-server.example.org

      Close the connection with ``exit``, then register the server:

      .. code-block:: bash

          dallinger docker-ssh servers add --host my-server.example.org --user ubuntu

      This takes a few minutes. If Docker is not installed, Dallinger installs
      it, including the Docker Compose plugin, and adds your user to the
      ``docker`` group. The ``--host`` value is the name you pass as
      ``--server`` in later commands, and experiments are served at
      ``https://<app>.my-server.example.org``.

      You can register a server by IP address instead of a name. Deployments
      then need ``--dns-host`` as well; see :ref:`ssh_server_addresses`.

   .. tab-item:: AWS (automatic)
      :sync: aws

      ``dallinger ec2 provision`` creates an EC2 instance, points a subdomain
      of your domain at it and registers it. The instance costs money until
      you tear it down. Check the AWS console after each study for instances
      you have forgotten.

      **AWS credentials.** Create an IAM user with these permissions:

      - ``AmazonEC2FullAccess``
      - ``AmazonRoute53FullAccess``
      - ``AmazonS3FullAccess``, only if experiments store data or assets in S3

      Anyone who obtains these keys can run up charges on your account, so
      keep the permissions this narrow and delete keys you no longer use. Add
      the keys to ``~/.dallingerconfig``. ``aws_region`` sets the default
      region (``us-east-1`` if omitted):

      .. code-block:: ini

          [AWS]
          aws_access_key_id = your-access-key-id
          aws_secret_access_key = your-secret-access-key
          aws_region = us-east-1

      **Domain.** Register a domain in Route 53, or host an existing domain's
      DNS there, and wait until the registration is complete. Each server
      gets a subdomain of it, such as ``memory-lab.cool-psychology.org``.
      Dallinger looks up the hosted zone from the last two parts of the name,
      so the domain must have the form ``cool-psychology.org``.

      **Key pair.** In the EC2 console, create a key pair and download its PEM
      file to ``~/.ssh`` (for example ``~/.ssh/cool-psychology.pem``). Set
      ``ec2_default_pem`` to the key pair's name, without path or extension,
      and ``server_pem`` to the file. Dallinger finds the file by this name,
      as ``~/.ssh/<ec2_default_pem>.pem``, so the file name must match the
      key pair name. Keep only one ``server_pem`` line in
      ``~/.dallingerconfig``.

      .. code-block:: ini

          [EC2]
          ec2_default_pem = cool-psychology
          server_pem = ~/.ssh/cool-psychology.pem

      If the key pair does not exist in the region you provision in, Dallinger
      imports it there from the local file.

      **Provision.** List the regions with ``dallinger ec2 list regions`` and
      choose the one closest to your participants. Then run:

      .. code-block:: bash

          dallinger ec2 provision \
              --name memory-lab \
              --region us-east-1 \
              --dns-host memory-lab.cool-psychology.org \
              --type m7i.xlarge

      ``--name`` labels the instance in AWS and may contain only lowercase
      letters, digits and hyphens. ``--type`` defaults to ``m5.xlarge``;
      ``m7i.large`` suits a pilot and ``m7i.xlarge`` a live study.
      ``--storage`` sets the disk size in GB (default 32); increase it if the
      experiment keeps many participant uploads on the server with
      ``LocalStorage``.

      Provisioning takes a few minutes. The server is registered twice, under
      its AWS hostname and under the ``--dns-host`` name, so always pass the
      ``--dns-host`` name as ``--server`` (here
      ``memory-lab.cool-psychology.org``). Experiments are served at
      ``https://<app>.memory-lab.cool-psychology.org``. For the other ``ec2``
      commands and what provisioning does, see
      :doc:`/deploy/reference/aws_automatic_provisioning`.

      .. lab-note::

         Your lab administrator creates the IAM credentials and tells you the
         lab's shared domain, key pair and security group
         (``ec2_default_security_group``). Name servers so that others can
         tell who owns them, in the form ``name-experiment-version``, for
         example ``--name alice-melody-batch2``, and use your own subdomain
         of the lab domain, for example ``--dns-host alice.<lab-domain>``.

Checking the server
-------------------

List the registered servers, then connect to yours:

.. code-block:: bash

    dallinger docker-ssh servers list
    psynet apps ssh --server my-server.example.org

A new server reports ``No apps found.`` To check the whole path, deploy a
pilot of any experiment and open ``https://<app>.<server>`` as described in
:doc:`/deploy/running_a_study`. The first deployment also starts the log
viewer at ``https://logs.<server>``; its username is ``dallinger`` and its
password is the dashboard password of that first deployment. To change it,
run ``dallinger docker-ssh set-dozzle-password --server <server>``.

Stopping and removing the server
--------------------------------

.. tab-set::
   :sync-group: server

   .. tab-item:: Existing server
      :sync: existing

      Destroy the apps on the server with ``psynet destroy ssh`` once you
      have exported their data. To forget the server on your computer, run:

      .. code-block:: bash

          dallinger docker-ssh servers remove --host my-server.example.org

      This changes nothing on the server itself.

   .. tab-item:: AWS (automatic)
      :sync: aws

      To pause a multi-day study overnight, stop the instance and start it
      again the next day. A stopped instance still incurs a small storage
      charge.

      .. code-block:: bash

          dallinger ec2 stop --name memory-lab --region us-east-1 \
              --dns-host memory-lab.cool-psychology.org
          dallinger ec2 start --name memory-lab --region us-east-1 \
              --dns-host memory-lab.cool-psychology.org

      Stopping removes the DNS records and starting recreates them. The AWS
      hostname changes when the instance restarts, so keep using the
      ``--dns-host`` name as ``--server``. The experiments restart with the
      instance; check that they work before recruiting again.

      When the study is over, export all data, then terminate the instance:

      .. code-block:: bash

          dallinger ec2 teardown --name memory-lab --region us-east-1 \
              --dns-host memory-lab.cool-psychology.org

      Teardown deletes the instance with every database on it, removes the
      DNS records and removes both server registrations. Data you have not
      exported is lost. Teardown only finds a running instance, so start a
      stopped server first with ``dallinger ec2 start``. ``dallinger ec2 list
      instances --running`` shows the instances that are still running.
