.. _deploy_troubleshooting:
.. highlight:: shell

===============
Troubleshooting
===============


No space left on device
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you see a ``No space left on device`` or ``You don't have enough free space`` error when executing Docker commands, the solution
is typically to prune your local Docker storage. You can do this by running the following:

.. code:: bash

    docker system prune
    docker system prune --volumes


Error parsing launch response
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you see an error like this:

.. code:: bash

    Error parsing response from https://dlgr-cdd607db-d584-551a.herokuapp.com/launch, check web dyno logs for details: <!DOCTYPE html>
        <html>
          <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <meta charset="utf-8">
            <title>Application Error</title>
            <style media="screen">
              html,body,iframe {
                margin: 0;
                padding: 0;
              }
              html,body {
                height: 100%;
                overflow: hidden;
              }
              iframe {
                width: 100%;
                height: 100%;
                border: 0;
              }
            </style>
          </head>
          <body>
            <iframe src="//www.herokucdn.com/error-pages/application-error.html"></iframe>
          </body>
        </html>
    Traceback (most recent call last):
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/requests/models.py", line 971, in json
        return complexjson.loads(self.text, **kwargs)
      File "/usr/lib/python3.10/json/_init_.py", line 346, in loads
        return _default_decoder.decode(s)
      File "/usr/lib/python3.10/json/decoder.py", line 337, in decode
        obj, end = self.raw_decode(s, idx=_w(s, 0).end())
      File "/usr/lib/python3.10/json/decoder.py", line 355, in raw_decode
        raise JSONDecodeError("Expecting value", s, err.value) from None
    json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
    During handling of the above exception, another exception occurred:
    Traceback (most recent call last):
      File "/home/r/.virtualenvs/dlgr_env2/bin/dallinger", line 8, in <module>
        sys.exit(dallinger())
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/click/core.py", line 1130, in _call_
        return self.main(*args, **kwargs)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/click/core.py", line 1055, in main
        rv = self.invoke(ctx)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/click/core.py", line 1657, in invoke
        return _process_result(sub_ctx.command.invoke(sub_ctx))
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/click/core.py", line 1404, in invoke
        return ctx.invoke(self.callback, **ctx.params)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/click/core.py", line 760, in invoke
        return __callback(*args, **kwargs)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/dallinger/command_line/utils.py", line 72, in wrapper
        return f(*args, **kwargs)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/dallinger/command_line/_init_.py", line 266, in wrapper
        return f(**kwargs)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/dallinger/command_line/_init_.py", line 104, in wrapper
        result = func(*args, **kwargs)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/dallinger/command_line/_init_.py", line 294, in deploy
        return _deploy_in_mode(
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/dallinger/command_line/_init_.py", line 246, in _deploy_in_mode
        return deploy_sandbox_shared_setup(
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/dallinger/deployment.py", line 218, in deploy_sandbox_shared_setup
        launch_data = _handle_launch_data(launch_url, error=log)
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/dallinger/deployment.py", line 48, in _handle_launch_data
        launch_data = launch_request.json()
      File "/home/r/.virtualenvs/dlgr_env2/lib/python3.10/site-packages/requests/models.py", line 975, in json
        raise RequestsJSONDecodeError(e.msg, e.doc, e.pos)
    requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

It means that an error occurred when PsyNet/Dallinger tried to launch the experiment on the remote server.
The 'real' error message can be found on the remote server. If you are using Heroku, you can find
the real error message by looking in the Papertrail logs. If you are using an SSH server,
you can find the real error message by SSHing to the server, executing ``cd ~/dallinger/your-app-name``,
then executing ``docker compose logs``.

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

Try re-adding your PEM key to your SSH agent by running:

.. code:: bash

   ssh-add -K ~/.ssh/<your-key-name>.pem

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
