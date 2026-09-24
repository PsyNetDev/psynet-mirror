.. _aws_automatic_provisioning:

==========================
AWS automatic provisioning
==========================

Once your AWS account and Dallinger credentials are configured (see
:doc:`Setting up an AWS server </running_studies/reference/aws_server_setup>`), PsyNet can
provision and tear down EC2 servers for you automatically via Dallinger's
``ec2`` commands. This is convenient for cloud deployments and avoids
manually creating instances through the AWS console every time.

EC2 servers operate on a pay-as-you-go model. You are charged while the
server is running, so it is important to monitor usage and tear the
server down when you are finished.

The EC2 workflow includes:

1. Choose the region closest to your participants.

2. Set up a server in this region. This is provisioning.

3. Deploy or debug to this server with PsyNet.

4. Monitor your experiment and export your data regularly.

5. Wait for the experiment to finish, or finish it manually.

6. Export once more and save your results.

7. Terminate the server. This is teardown.

Selecting the region
=====================

First, decide which region to deploy to. To list the available regions,
run:

.. code:: bash

   dallinger ec2 list regions

For example, choose ``us-east-1`` for participants in the eastern United
States. In general, the server should be close to where your
participants are located.

Listing instances
==================

Instances can have the following states: pending, running,
shutting-down, terminated, stopping, stopped. You can list all instances
with:

.. code:: bash

   dallinger ec2 list instances

To only list instances which are running, run:

.. code:: bash

   dallinger ec2 list instances --running

You can also filter by region:

.. code:: bash

   dallinger ec2 list instances --region <region>

Or filter to only running instances in a specific region:

.. code:: bash

   dallinger ec2 list instances --region <region> --running

Provisioning an instance
==========================

Once you choose an EC2 instance type, provision the server. After
provisioning, you will be charged until you stop or terminate the
instance.

.. important::

   Export your data before you tear down the server. If you do not
   export the data first, the data are lost and there is no way to
   retrieve them.

Before you teardown the instance make sure:

-  The experiment is stopped on the recruiter. For example, in Prolific
   the experiment should be stopped and no longer active.

-  You have exported the data and run ``export.py`` (or your
   equivalent) to check that the exported data are usable.

You can provision an EC2 instance on demand:

.. code:: bash

   dallinger ec2 provision --name <server_name> --region <region> --dns-host <your-subdomain>.<your-domain> --type <type>

Pick a server name that is easy to recognize. Start the name with your
own name or a short identifier so others can tell who deployed it. A
name like ``alice-melody-batch2`` is good; ``melody123`` is not. The
recommended convention is:

.. code:: text

   name-experiment-version

For example, to collect data from participants in the US:

.. code:: bash

   dallinger ec2 provision --name alice-melody-batch2 --region us-west-2 --dns-host alice.<your-domain> --type <type>

Specify a custom subdomain that reflects your identity so the server URL
is recognizable. The full experiment URL will combine the subdomain and
the app name, for example: ``alice-melody-batch2.alice.<your-domain>``.

Choose the instance type according to your needs. ``m7i.large`` is
recommended for debugging, and ``m7i.xlarge`` is recommended for live
deployment. For example:

.. code:: bash

   dallinger ec2 provision --name alice-melody-batch2 --region eu-west-3 --dns-host alice.<your-domain> --type m7i.xlarge

If you use ``LocalStorage`` instead of S3 storage and the experiment
creates large stimuli, such as iterative singing or GSP experiments,
make sure the instance has enough storage. If the instance runs out of
storage during the experiment, the experiment may crash. Alternatively,
use ``S3Storage`` for experiments with many assets. If the experiment
does not create new assets, the default storage is usually sufficient.
You can find instance storage information in the AWS EC2 documentation:
https://aws.amazon.com/ec2/instance-types/.

Usually, PsyNet should be responsible for uploading assets to storage.
For more information, see the :doc:`Assets guide
</guides/trials/assets>`.

During the provisioning, all steps are printed to the terminal. At the
end, you should see something like this printed in the terminal:

.. code:: text

   Connecting to alice.<your-domain>

   Connected.

   DNS record set up!

   Host registered in dallinger

   Provisioning complete! Time taken: 192.402161359787. alice-step-en is
   ready at ec2-52-91-24-127.compute-1.amazonaws.com

You can use Dozzle to view experiment logs and monitor server
performance. To get the Dozzle URL, add ``logs.`` in front of the DNS
hostname. For example:

.. code:: bash

   logs.alice.<your-domain>

Stopping and starting an instance
====================================

For multi-day deployments, you can stop the EC2 instance overnight to
reduce costs. While you won't be charged for running the server during
the stopped period, you will still incur minimal charges for storage.
Do not forget to terminate the server when the experiment is done; see
:ref:`Terminating an instance <aws_automatic_teardown>` below.

To stop the instance:

.. code:: bash

   dallinger ec2 stop --name <server_name> --region <region> --dns-host <your-subdomain>.<your-domain>

The next day, start the instance again. This reboots all Docker
containers and experiments, so double-check that the experiment still
works after the restart. To start the instance:

.. code:: bash

   dallinger ec2 start --name <server_name> --region <region> --dns-host <your-subdomain>.<your-domain>

.. _aws_automatic_ssh_into_instance:

SSH into the instance
=======================

To SSH into the EC2 server manually, use:

.. code:: bash

   ssh <SERVER_URL>

For example:

.. code:: bash

   ssh ec2-18-170-223-29.eu-west-2.compute.amazonaws.com

SSH access is useful if you need to restart a Docker container or
inspect assets on the server.

.. _aws_automatic_teardown:

Terminating an instance
=========================

Once you have finished with your experiment, terminate the EC2 server
to avoid ongoing charges. EC2 servers incur costs as long as they are
running.

.. important::

   You must export all data before teardown. Once the server is
   terminated, any data that was not exported is permanently lost.

.. code:: bash

   dallinger ec2 teardown --name <server_name> --region <region> --dns-host <your-subdomain>.<your-domain>

If you need to delete the app without tearing down the server (for
example, when redeploying from archive on the same server, or reusing
assets already stored there), use ``psynet destroy ssh`` instead:

.. code:: bash

   psynet destroy ssh --app <app_name> --server <your-subdomain>.<your-domain>

.. note::

   **Destroy the app** when you have exported the data and will need to
   reuse the same server, for example when redeploying from archive
   (e.g., when assets are stored on the server).

.. note::

   **Teardown the server directly** when you have exported all the data
   and will not need the server anymore.

.. warning::

   Every time you destroy an app you also need to stop the related
   Prolific experiment. Each redeploy creates a new Prolific experiment,
   and you can exclude participants from earlier deploys via the
   Prolific platform.

If you used an internal or physical server rather than EC2, there is no
server to tear down; simply delete the app once your experiment is done
and you have exported all data:

.. code:: bash

   psynet destroy ssh --app <app_name> --server <your-server-hostname>

Advanced: custom instances
=============================

For certain use cases, such as setting up your own synthesis server, you
may want to programmatically configure a custom EC2 server. This is an
advanced workflow that depends on your lab's infrastructure and should
be documented in your lab's internal deployment documentation. Most
experiments should use the standard provisioning command described
above.
