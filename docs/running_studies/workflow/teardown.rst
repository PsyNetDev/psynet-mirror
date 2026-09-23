Teardown
========

The teardown steps depend on the server type you used. For the full
command reference (EC2 teardown, destroying an app without tearing down
the server, and internal/physical server cleanup), see
:ref:`Terminating an instance <aws_automatic_teardown>` in the
deployment reference.

Before you tear anything down, make sure:

-  You have exported all data. **Once an EC2 server is terminated, any
   data that was not exported is permanently lost.**

-  The experiment is stopped on the recruiter (for example, in Prolific
   the experiment should be stopped and no longer active).

-  Every time you destroy an app, you also stop the related Prolific
   experiment. Each redeploy creates a new Prolific experiment, and you
   can exclude participants from earlier deploys via the Prolific
   platform.

Quick reference:

.. code:: bash

   # Terminate an EC2 server entirely
   dallinger ec2 teardown --name <server_name> --region <region> --dns-host <your-subdomain>.<your-domain>

   # Delete an app without tearing down the server (e.g. before redeploying from archive)
   psynet destroy ssh --app <app_name> --server <your-subdomain>.<your-domain>

For multi-day deployments, you can stop the EC2 instance overnight
instead of tearing it down; see the stop/start commands in
:doc:`Provisioning <provisioning>`.
