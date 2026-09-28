.. _aws_automatic_provisioning:

==========================
AWS automatic provisioning
==========================

Dallinger's ``ec2`` commands create, pause and delete EC2 servers for PsyNet
experiments. They need the AWS credentials, domain, key pair and
``~/.dallingerconfig`` settings described in
:doc:`/deploy/setting_up_a_server`.

Most commands select an instance with ``--name`` (the name given at
provisioning) or ``--dns`` (the instance's AWS hostname), plus ``--region``.
Without ``--region``, Dallinger uses ``aws_region`` from your configuration,
or ``us-east-1``.

Listing regions, instance types and instances
=============================================

.. code:: bash

   dallinger ec2 list regions
   dallinger ec2 list instance_types --region <region>

Instances can have the following states: pending, running, shutting-down,
terminated, stopping, stopped. To list your instances:

.. code:: bash

   dallinger ec2 list instances

Filter them with ``--region <region>`` and with any of ``--running``,
``--stopped`` and ``--terminated``, for example:

.. code:: bash

   dallinger ec2 list instances --region <region> --running

Provisioning an instance
========================

.. code:: bash

   dallinger ec2 provision --name <server_name> --region <region> --dns-host <subdomain>.<your-domain> --type <type>

Options:

``--name``
   Name of the instance in AWS (required). Only lowercase letters, digits and
   hyphens are allowed. Provisioning fails if a running instance already has
   this name.
``--region``
   AWS region.
``--type``
   Instance type (default ``m5.xlarge``). See
   `EC2 instance types <https://aws.amazon.com/ec2/instance-types/>`_ for the
   options and their storage.
``--storage``
   Disk size in GB (default 32).
``--image_name``
   Machine image: an AMI name, AMI ID or SSM parameter. The default is
   Canonical's current Ubuntu 24.04 image.
``--security_group_name``
   Security group to attach. The default is the ``ec2_default_security_group``
   configuration value, or ``dallinger``.
``--dns-host``
   Name to create in Route 53, for example ``memory-lab.cool-psychology.org``.

Provisioning runs these steps and prints each one to the terminal:

1. If ``--dns-host`` is given, checks that Route 53 has a hosted zone for its
   last two parts (for example ``cool-psychology.org``). If records for the
   name already exist, Dallinger asks before overwriting them, because they
   may belong to another running server.
2. Creates the security group if it does not exist in the region, allowing
   incoming traffic from anywhere on ports 22, 80, 443 and 5000.
3. Imports the key pair named by ``ec2_default_pem`` from
   ``~/.ssh/<ec2_default_pem>.pem`` if it does not exist in the region.
4. Boots the instance, attaches the security group and grows the disk to
   ``--storage``.
5. Checks that ``dashboard_user`` and ``dashboard_password`` are set, then
   installs Docker on the instance. If this check fails, the instance is
   already running; set the credentials, tear the instance down and
   provision again.
6. Creates CNAME records for the ``--dns-host`` name and its wildcard
   (``*.<dns-host>``), pointing at the instance's AWS hostname.
7. Registers the server with Dallinger under both its AWS hostname and the
   ``--dns-host`` name.

At the end, you should see something like this:

.. code:: text

   Provisioning complete! Time taken: 192.402161359787. memory-lab is
   ready at ec2-52-91-24-127.compute-1.amazonaws.com

If the experiment stores large or many assets with ``LocalStorage``, for
example iterative singing or GSP experiments, make sure that the disk is
large enough; an experiment can crash when the disk fills up. Use
``S3Storage`` for experiments with many assets, or increase the storage of
an existing instance:

.. code:: bash

   dallinger ec2 increase-storage --name <server_name> --region <region> --storage <size_in_gb>

The new size must be larger than the current one. For more on storage
back-ends, see the :doc:`Assets guide </code/trials/assets>`.

Stopping, starting and restarting an instance
=============================================

.. code:: bash

   dallinger ec2 stop --name <server_name> --region <region> --dns-host <subdomain>.<your-domain>
   dallinger ec2 start --name <server_name> --region <region> --dns-host <subdomain>.<your-domain>

``stop`` removes the DNS records for ``--dns-host`` and stops the instance,
keeping the server registrations. AWS continues to charge for the instance's
storage while it is stopped. ``start`` waits until the instance has stopped,
starts it and recreates the DNS records, pointing them at the instance's new
AWS hostname. Pass ``--name`` to ``start``. Docker restarts the experiments
with the instance.

``restart`` reboots a running instance without changing its hostname or DNS
records:

.. code:: bash

   dallinger ec2 restart --name <server_name> --region <region>

.. _aws_automatic_ssh_into_instance:

SSH into the instance
=====================

Log in with the key pair's PEM file as the ``ubuntu`` user, using either the
``--dns-host`` name or the AWS hostname:

.. code:: bash

   ssh -i ~/.ssh/<ec2_default_pem>.pem ubuntu@<subdomain>.<your-domain>

SSH access is useful if you need to restart a Docker container or inspect
assets on the server; see :doc:`/deploy/reference/ssh_server`.

.. _aws_automatic_teardown:

Terminating an instance
=======================

.. code:: bash

   dallinger ec2 teardown --name <server_name> --region <region> --dns-host <subdomain>.<your-domain>

``teardown`` terminates the instance, which deletes its disk with every
experiment database on it. It then removes the DNS records for ``--dns-host``
and both server registrations. Without ``--dns-host``, the DNS records and the
``--dns-host`` registration stay behind. Export all data first; see
:doc:`/deploy/running_a_study`.

Custom machine images
=====================

To start from your own machine image, pass its AMI ID or name with
``--image_name``. Most experiments should use the default Ubuntu image.
