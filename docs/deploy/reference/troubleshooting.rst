.. _deploy_troubleshooting:
.. highlight:: shell

===========================
Troubleshooting deployments
===========================

When a deployment fails on the server, the real error is usually in the logs
of the app's ``web`` service. Read them over SSH with the log command that
the deployment prints (see :ref:`ssh_server_working_over_ssh`) or, on servers
with classic ingress, in Dozzle at ``https://logs.<server DNS name>``. Apps with
Cloudflare ingress have no Dozzle (see :ref:`ssh_server_cloudflare`).

DNS resolution error
^^^^^^^^^^^^^^^^^^^^

Before deploying, Dallinger checks that ``<app>.<dns-host>`` resolves to the
server's IP address. If it doesn't, check that the wildcard record
``*.<dns-host>`` exists and points at the server, and that ``--server`` and
``--dns-host`` are correct. After ``dallinger ec2 provision``, or after
reusing a name for a new server, wait about five minutes for DNS to update and
try again.

.. _deploy_troubleshooting_not_set_up:

Server is not set up for this classic-ingress deploy
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Deployments don't set up the server's shared services, so Dallinger stops
before building the image if the deployment needs something they lack. This
happens on a server that an older Dallinger registered or provisioned but
never deployed to. It also happens on a server set up by an older Dallinger
when the experiment is served at the server's own DNS name (no ``--app``), or
when the older Dallinger's last deployment there was such a root-domain one.
Run the command that the message names, when no classic experiment on the
server is live, then deploy again:

.. code:: bash

    dallinger docker-ssh servers upgrade --host my-server.example.org

The same applies if the message says that an older Dallinger version has
rewritten the shared files. See :ref:`ssh_server_shared_services`.

If the message says that the server's ``Caddyfile`` does not serve the
expected name, the server may already serve another DNS name, for example a
server registered by IP address whose earlier deployments used ``--dns-host
nip.io``. Save that name, which restarts nothing, and deploy again:

.. code:: bash

    dallinger docker-ssh servers add --host 121.101.152.23 --user ubuntu --dns-host nip.io

No Let's Encrypt contact email
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A deployment or server command stops with ``No Let's Encrypt contact email
for <server>`` when no email is saved with the server and
``contact_email_on_error`` is missing or a placeholder, such as the
``XXX@gmail.com`` in PsyNet's experiment template. This often happens on a
server registered by an older Dallinger. Set a real ``contact_email_on_error``
in ``~/.dallingerconfig`` (see :doc:`/deploy/setting_up_a_server`), or save an
email with the server, which restarts nothing, and deploy again:

.. code:: bash

    dallinger docker-ssh servers add --host my-server.example.org --user ubuntu --contact-email you@example.org

Deployment fails with ``PermissionError``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the traceback ends with ``PermissionError: [Errno 13] Permission denied``
at ``sftp.putfo(..., "dallinger/docker-compose.yml")``, the server was set up
or upgraded by a newer Dallinger, which left its shared files read-only (see
:ref:`upgrading_an_existing_server`), and your Dallinger is too old to deploy
there. The deployment stopped before changing anything shared. Don't make the
files writable. Instead, update the experiment's PsyNet pin, which brings a
newer Dallinger (see :ref:`dependencies_updating_psynet`), and deploy again.
An older Dallinger may first offer to destroy the server's other experiments;
decline.

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

``server_pem`` cannot be loaded
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Dallinger checks the key in ``server_pem`` before connecting. If it is a DSA
key, Dallinger stops with an error saying that the key ``is a DSA key, which
Dallinger can no longer use``. Replace it as described in
:ref:`replacing-a-dsa-key`.

If connecting fails with ``not a valid OPENSSH private key file`` instead, the
file may be damaged or may not be a private key. Check it:

.. code:: bash

    ssh-keygen -l -f ~/.ssh/my-server.pem

If ``ssh-keygen`` says the file is not a key file, point ``server_pem`` at the
right private key. If the output ends in ``(DSA)``, replace the key as
described in :ref:`replacing-a-dsa-key`.

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
