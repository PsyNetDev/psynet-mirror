.. _deploy_troubleshooting:
.. highlight:: shell

===========================
Troubleshooting deployments
===========================


No space left on device
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you see a ``No space left on device`` or ``You don't have enough free space`` error when executing Docker commands on the **remote server**, prune Docker storage there:

.. code:: bash

    docker system prune
    docker system prune --volumes

For the same error during a **local** Docker build, see
:ref:`Docker no space left on device <develop_troubleshooting_docker_space>`.


Error parsing launch response
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you see an error like this:

.. code:: bash

    Error parsing response from https://your-app-name.your-server.org/launch, check web dyno logs for details: <!DOCTYPE html>
    ...
    requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

It means that an error occurred when PsyNet/Dallinger tried to launch the experiment on the remote server.
The 'real' error message can be found on the remote server: SSH to the server, run
``cd ~/dallinger/your-app-name``, then run ``docker compose logs``.

Stuck during database initialization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

We have reports of experiment deployments getting stuck at:

::

  Experiment read-prescreener-demo5 started. Initializing database
  Database initialized


We have heard that the problem resolves if you restart the remote server with the following command:

::
  
  sudo reboot

though note that this may interrupt pre-existing deployed experiments.
This problem needs further investigation.


Stuck during experiment launch
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the ``psynet deploy ssh`` or ``psynet debug ssh`` command gets stuck partway through, it's normally worth
checking the docker compose logs on the remote server:

::

  cd ~/dallinger/<your-app-name>
  docker compose logs

If the error occurs during "Launching experiment", beware that the last error may not be indicative of the real issue,
because it may instead reflect errors from the launch command repeatedly trying to relaunch over a previous partial launch.
It's a good idea to scroll up to the first issue in this case.
Note also that if your command fails early on then you might instead see Docker compose logs from the previous time 
you tried to launch the experiment.

Note: A common problem is that you are using a different version (e.g. branch or commit) of PsyNet locally than on the remote server. 
This can lead to unexpected errors. You should check your ``requirements.txt`` before deploying and verify that it 
gives the same branch/commit that you have selected locally.

If the launch appears stuck at "Launching experiment" for more than a
few minutes, a common cause is that ``nip.io`` has hit a quota limit and
is refusing to provide an HTTPS address. Other common causes include an
invalid server name or incorrect recruiter parameters. If the terminal
does not show a clear error, the Dozzle logs (see above) usually contain
a more useful message.

I cannot access my server anymore
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Try re-adding your PEM key to your SSH agent. On macOS, run:

.. code:: bash

   ssh-add --apple-use-keychain ~/.ssh/<your-key-name>.pem

On Linux, run:

.. code:: bash

   ssh-add ~/.ssh/<your-key-name>.pem

Replace ``<your-key-name>`` with the name of your PEM file (e.g., the
file configured in your ``~/.dallingerconfig``).

Docker connection errors when running debug or deploy
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you see this error after running ``psynet debug ssh`` or
``psynet deploy ssh``:

.. code:: text

   docker.errors.DockerException: Error while fetching server API version:
   ('Connection aborted.', ConnectionRefusedError(61, 'Connection refused'))

Make sure Docker Desktop is running.

If you instead see:

.. code:: text

   docker.errors.DockerException: Error while fetching server API
   version: ('Connection aborted.', PermissionError(13, 'Permission denied'))

Changing permissions to the Docker socket has resolved this issue in the
past.

Port 5000 is already in use
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Disable AirDrop receiver on macOS. Alternatively, stop any other
experiment running in another terminal or IDE window. To kill all
running Python processes you can run:

.. code:: bash

   killall python

or

.. code:: bash

   killall Python

My server restarted and my experiment is no longer running
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

All experiments are stored under ``~/dallinger``. SSH into the server,
navigate to the experiment directory, and run ``docker compose up`` to
restart the experiment containers.

I am unable to connect to my AWS EC2 instance via SSH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A timeout often indicates a networking or internal system issue that can
be resolved with a reboot. Steps:

1. Install the AWS CLI.

2. Configure it with your credentials:

   .. code:: bash

      aws configure

3. Find the instance ID:

   .. code:: bash

      dallinger ec2 list instances

4. Reboot the instance:

   .. code:: bash

      aws ec2 reboot-instances --instance-ids <INSTANCE_ID>
