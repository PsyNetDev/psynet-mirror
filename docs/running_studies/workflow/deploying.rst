Launch the experiment
=====================

Sanity check
------------

Version control
^^^^^^^^^^^^^^^

Before you deploy your experiment, you need to:

-  Have a Git repository. If the experiment is not yet in Git, create a
   repository with:

   .. code:: bash

      git init

-  Commit all changes. There should be no staged or modified files when
   you deploy.

-  Define a remote repository and push your commits to it.

See :doc:`Prerequisites <prerequisites>` for Git setup instructions.

Requirements and dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Make sure the PsyNet and Dallinger versions you tested locally match the
versions listed in ``requirements.txt`` and ``constraints.txt``. If you
change ``requirements.txt``, regenerate and commit ``constraints.txt``:

.. code:: bash

   psynet generate-constraints

For the canonical dependency workflow, see
:doc:`Dependencies </guides/project/dependencies>`. Before
deploying, test the exact environment locally with ``psynet debug local``
and complete the testing checklist in
:doc:`general_deployment_process`.

Remote debug
^^^^^^^^^^^^

Before deployment, you need to make sure your experiment runs
successfully on a remote server. Make sure you did all types of
:ref:`tests <lab-deployment-test>` and thus did a remote debug.

.. _lab-deployment-actual-deployment:

Run the deployment command
--------------------------

-  Set up the experiment for live deployment. For example, restore the
   production number of trials or networks if you reduced them during
   hotair testing.

-  Set the ``recruiter`` config parameter to the intended live recruiter,
   for example ``prolific`` or ``lucid``. Note: PsyNet still uses the
   name ``lucid`` internally for CINT deployments; consult the
   :doc:`recruiter-specific steps <recruiter_specific_deployment_steps>`
   for the correct value for your recruiter.

-  Double-check all settings mentioned in
   :doc:`recruiter-specific steps <recruiter_specific_deployment_steps>`.

-  Deploy from the experiment directory, choosing the server according
   to your setup; see :doc:`Provisioning <provisioning>`. For the full
   deploy command syntax, expected output, and what to do if the launch
   gets stuck, see :ref:`Deploying experiments via SSH <ssh_server>`.

   .. code:: bash

      psynet deploy ssh --app <app_name> --dns-host <your-subdomain>.<your-domain> --server <your-subdomain>.<your-domain>

Once deployed, save the dashboard link that is printed in the terminal
so that you are able to :doc:`monitor <monitoring_and_managing>` the
experiment during data collection.

Redeployment from archive
-------------------------

If you need to redeploy from an archive, see
:doc:`Deploying from archive </running_studies/reference/deploy_from_archive>`.
