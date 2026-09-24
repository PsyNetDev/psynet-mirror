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

For the commands themselves, see
:ref:`Terminating an instance <aws_automatic_teardown>`.
For multi-day deployments you can stop the EC2 instance overnight
instead of tearing it down; see :doc:`Provisioning <provisioning>`.
