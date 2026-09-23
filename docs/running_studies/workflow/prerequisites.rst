Prerequisites (one-time setup)
==============================

This page describes the one-time setup required to run experiments using
the lab deployment workflow. You only need to complete this setup once.

PsyNet installation
-------------------

Install PsyNet before following the lab deployment workflow. Most users
should follow the :ref:`official installation guide <installation>`,
which covers the supported virtual-environment setup. The Docker
installation route is documented separately but is considered legacy for
new users.

Required software and accounts
------------------------------

Before deploying experiments, make sure the following standard setup is
complete:

- Install PsyNet using the :ref:`official installation guide
  <installation>`.
- Set up your editor using the :ref:`development workflow
  <development_workflow>`. Cursor is the strongest recommendation;
  VSCode is the closest alternative; PyCharm is supported but no longer
  the default recommendation.
- Learn the Git workflow using the :doc:`PsyNet Git tutorial
  </guides/project/version_control_with_git>`.
  Your experiment should be in a Git repository, committed, and pushed
  before deployment.
- Add your SSH key to GitLab if your lab uses SSH-based Git access; see
  :ref:`additional developer installation steps
  <additional_developer_installation>`.
- Confirm that you can run your experiment locally with
  ``psynet debug local`` before trying a server deployment.
- Install Docker Desktop if your deployment route or experiment template
  uses Docker-based commands.
- If your lab uses Docker images for deployment, log into the relevant
  Docker registry. For a GitLab registry this is usually:

  .. code:: bash

     docker login registry.gitlab.com

  See the :ref:`SSH server guide <ssh_server>` for Docker registry
  configuration details.

Lab access checklist
--------------------

Ask your lab administrator to confirm that:

- You have access to the lab's GitLab group or repository namespace.
- You have access to the Docker registry used for experiment images, if
  your lab uses one.
- Your SSH key is registered wherever the lab requires it for GitLab,
  server access, or shared deployment resources.
- You have received the credential files needed for the lab's deployment
  environment.

Set credentials and server access keys
--------------------------------------

You will need a ``.dallingerconfig`` file in your home directory and a
PEM key file in your ``~/.ssh`` directory to access your lab's servers.

Your lab administrator should provide these files through a secure
channel (for example, an encrypted archive in a private credential
repository). The steps below assume your lab provides a credential
archive containing both files.

1. Obtain the credential archive from your lab administrator (e.g.,
   clone a private credential repository or download an encrypted
   archive).

2. Inside the archive there will be an encrypted file containing your
   credentials:

   .. image:: /_static/images/lab_deployments/image2.png
      :width: 8.5in

3. Enter the password provided by your lab administrator to decrypt the
   archive.

4. Inside you will find ``.dallingerconfig`` and a PEM key file (e.g.
   ``your-key.pem``).

5. Place ``.dallingerconfig`` in your home directory and ``your-key.pem``
   in your ``~/.ssh`` directory.

6. Set the correct permissions on the PEM file:

   .. code:: bash

      chmod 600 ~/.ssh/your-key.pem

   On Windows you may also need to run:

   .. code:: bash

      icacls C:\path\to\your-key.pem /inheritance:r /grant:r "%USERNAME%:R"

7. Add the following lines to your ``~/.dallingerconfig``, replacing the
   values with those provided by your lab administrator:

   .. code:: ini

      [EC2]
      ec2_default_security_group = <your-security-group>
      ec2_default_pem = <your-key-name>  # no path, just the name without extension

      [Server PEM file]
      server_pem = ~/.ssh/<your-key-name>.pem

   You can verify the PEM file is in the right place by running:

   .. code:: bash

      ls ~/.ssh/your-key.pem
