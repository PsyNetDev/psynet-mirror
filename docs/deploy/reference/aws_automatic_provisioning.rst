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
   dallinger ec2 list instances

``list instances`` shows every instance with its state (pending, running,
shutting-down, terminated, stopping or stopped). Filter it with ``--region
<region>`` and with any of ``--running``, ``--stopped`` and ``--terminated``.

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
   options.
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
   Without it, the server's DNS name is ``<public ip>.nip.io``, because Let's
   Encrypt does not issue certificates for AWS hostnames. The public IP
   changes when the instance is stopped and started, and nothing updates
   that name, so use ``--dns-host`` for a server you might stop.

Provisioning runs these steps and prints each one to the terminal:

1. Before booting anything, checks your local settings and stops if one is
   wrong:

   - ``server_pem`` must be the unencrypted private key in the local
     ``~/.ssh/<ec2_default_pem>.pem`` key file, because a new instance
     accepts only that key pair;
   - ``dashboard_password`` must be set (``dashboard_user`` defaults to
     ``admin``);
   - ``contact_email_on_error``, which Caddy gives Let's Encrypt, must be a
     real email address in ``~/.dallingerconfig`` or the environment, not a
     placeholder such as ``XXX@gmail.com``.

2. If ``--dns-host`` is given, checks that Route 53 has a hosted zone that
   the name ends with (for example ``cool-psychology.org``), using the
   longest match. If records for the
   name already exist, Dallinger asks before overwriting them, because they
   may belong to another running server. It also removes the name's entries
   from ``~/.ssh/known_hosts``.
3. Creates the security group if it does not exist in the region, allowing
   incoming traffic from anywhere on ports 22, 80, 443 and 5000.
4. Imports the key pair named by ``ec2_default_pem`` from
   ``~/.ssh/<ec2_default_pem>.pem`` if it does not exist in the region.
5. Boots the instance, attaches the security group and grows the disk to
   ``--storage``.
6. Creates CNAME records for the ``--dns-host`` name and its wildcard
   (``*.<dns-host>``), pointing at the instance's AWS hostname. If Route 53
   can't create them, it warns, says which records to create by hand, and
   carries on.
7. Over the AWS hostname, installs Docker on the instance and registers the
   server with Dallinger under that hostname, saving the ``--dns-host`` name
   (or ``<public ip>.nip.io``) as its DNS name. It sets up the shared
   services that classic-ingress experiments use, as ``dallinger docker-ssh
   servers add`` does (see :ref:`ssh_server_shared_services`), and prints the
   log viewer's password once. With ``--dns-host``, it also registers the
   server under that name.

A classic deployment checks that the experiment's address resolves to the
server, whichever ``--server`` you use. With ``--dns-host``, you can deploy
once your computer resolves the new DNS records (up to about five minutes, or
15 if you looked a name up before it existed); without it, straight away.

If anything fails once the instance is launched, including Ctrl-C, the
instance keeps running and costs money. Provisioning then prints the
``dallinger ec2 teardown`` command that removes it (or says to terminate it
in the EC2 console while it may still be starting). If the setup had started,
it also prints the ``dallinger docker-ssh servers add`` commands that finish
the setup instead. Fix the problem, then run one or the other.

At the end, you should see something like this:

.. code:: text

   Provisioning complete in 192 seconds. memory-lab is ready at
   ec2-52-91-24-127.compute-1.amazonaws.com

Increasing storage
==================

Experiments that store many or large assets with ``LocalStorage``, for
example iterative singing or GSP experiments, can crash when the disk fills
up. Use ``S3Storage`` for them (see :doc:`/code/trials/assets`), or grow the
disk of a running instance:

.. code:: bash

   dallinger ec2 increase-storage --name <server_name> --region <region> --storage <size_in_gb>

The new size must be larger than the current one.

Stopping, starting and restarting an instance
=============================================

.. code:: bash

   dallinger ec2 stop --name <server_name> --region <region>
   dallinger ec2 start --name <server_name> --region <region>

``stop`` removes the instance's DNS records and stops the instance, keeping
the server registrations. AWS continues to charge for the instance's storage
while it is stopped. ``start`` waits until the instance has stopped, starts it
and points the DNS records at the instance's new AWS hostname. Pass
``--name`` to ``start``: a stopped instance usually loses its AWS hostname,
so ``--dns`` rarely finds it. Docker restarts the experiments with the
instance.

Both commands use the DNS name saved when the instance was provisioned with
``--dns-host``. For an instance provisioned by an older Dallinger, or for
records you made by hand, pass ``--dns-host <subdomain>.<your-domain>``. An
instance provisioned without ``--dns-host`` has no records to update, and
its ``<public ip>.nip.io`` name stops working once the instance restarts
with a new IP.
``stop`` deletes only records that point at the instance. If Route 53 can't
update the records, both commands warn and carry on; ``start`` then says
which records to point at the instance by hand.

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

For what to do on the server, see :ref:`ssh_server_working_over_ssh`.

.. _aws_automatic_teardown:

Terminating an instance
=======================

.. code:: bash

   dallinger ec2 teardown --name <server_name> --region <region>

``teardown`` removes the instance's DNS records, terminates the instance,
which deletes its disk with every experiment database on it, and removes its
server registrations. Like ``stop``, it uses the saved DNS name; for an
instance provisioned by an older Dallinger, pass ``--dns-host
<subdomain>.<your-domain>``, or the DNS records and the ``--dns-host``
registration stay behind. If Route 53 fails, it warns and still terminates
the instance. Export all data first. Teardown only finds a running instance:
start a stopped one first, or terminate it in the AWS console and remove its
DNS records by hand.
