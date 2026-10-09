.. _deploy_troubleshooting:
.. highlight:: shell

===========================
Troubleshooting deployments
===========================

When a deployment fails on the server, the real error is usually in the logs
of the app's ``web`` service. Read them in Dozzle at ``https://logs.<server>``
or over SSH (see :ref:`ssh_server_working_over_ssh`).

DNS resolution error
^^^^^^^^^^^^^^^^^^^^

Before deploying, Dallinger checks that ``<app>.<dns-host>`` resolves to the
server's IP address. If it doesn't, check that the wildcard record
``*.<dns-host>`` exists and points at the server, and that ``--server`` and
``--dns-host`` are correct. After ``dallinger ec2 provision``, or after
reusing a name for a new server, wait about five minutes for DNS to update and
try again.

.. _deploy_troubleshooting_host_key:

Remote host identification has changed
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the server's name was used before by another machine, SSH refuses to
connect:

.. code:: text

    @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    @    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
    @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    ...
    Host key verification failed.

If you know that the name now points at a new server, remove the old key from
``~/.ssh/known_hosts``:

.. code:: bash

    ssh-keygen -R my-server.example.org

I cannot access my server anymore
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add the key from ``server_pem`` to your SSH agent again. On macOS:

.. code:: bash

   ssh-add --apple-use-keychain ~/.ssh/my-server.pem

On Linux:

.. code:: bash

   ssh-add ~/.ssh/my-server.pem

I am unable to connect to my AWS EC2 instance via SSH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A timeout often indicates a networking or internal system issue that a reboot
resolves. Find the instance name, then reboot the instance:

.. code:: bash

   dallinger ec2 list instances --running
   dallinger ec2 restart --name <server_name> --region <region>

For an instance you created in the AWS console, also check that its security
group allows SSH from your IP address.

Error parsing launch response
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code:: text

    Error parsing response from https://my-study.my-server.example.org/launch, check server logs for details.
    <!DOCTYPE html>
    ...
    requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

The experiment failed while launching on the server. The error is in the logs
of the ``web`` service.

Stuck after "Database initialized"
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Deployments have been reported to stop after printing:

.. code:: text

  Experiment my-study started.
  Initializing database...
  Database initialized.

Rebooting the server with ``sudo reboot`` has resolved this. The reboot
interrupts the other experiments on the server; Docker restarts them
afterwards.

Stuck during "Launching experiment"
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Read the logs of the ``web`` service. Launching retries after errors, so
later errors may only reflect a retry on top of an earlier partial launch;
scroll up to the first error. If the command failed early, the logs may
still be from a previous attempt.

Common causes are:

- a different PsyNet version (for example branch or commit) locally than in
  ``requirements.txt``;
- a PsyNet pin that omits the ``[experiment]`` extra, for example
  ``psynet==14.0.0`` instead of ``psynet[experiment]==14.0.0``. Deploying
  refuses that pin: the image would install only the command-line tools, and
  the clock process would fail to start;
- an invalid server name or incorrect recruiter settings;
- with ``--dns-host nip.io``, no HTTPS certificate being available for the
  nip.io name.

No space left on device
^^^^^^^^^^^^^^^^^^^^^^^

If Docker reports ``No space left on device`` or ``You don't have enough free
space`` on the **server**, remove unused images and volumes there:

.. code:: bash

    docker system prune
    docker system prune --volumes

If the disk keeps filling up, increase its size (see
:doc:`/deploy/reference/aws_automatic_provisioning` for EC2) or move the
experiment's assets to S3. For the same error during a **local** Docker build,
see :ref:`Docker no space left on device <develop_troubleshooting_docker_space>`.

My server restarted and my experiment is no longer running
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Docker normally restarts every app when the server starts. If an app is still
down, start the shared services and then the app:

.. code:: bash

   docker compose -f ~/dallinger/docker-compose.yml up -d
   cd ~/dallinger/my-study
   docker compose up -d
