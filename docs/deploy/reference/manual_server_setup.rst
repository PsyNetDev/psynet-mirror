.. _manual_server_setup:
.. _aws_server_setup:
.. _physical_server_setup:
.. highlight:: shell

===================
Manual server setup
===================

``dallinger ec2 provision`` creates a server, its DNS records and its
registration in one step. Any other server, whether an EC2 instance created in
the AWS console, a virtual machine from another provider or a physical
machine, needs the preparation below before it meets the requirements in
:doc:`/deploy/setting_up_a_server`. Register it as described there once it
does.

Key-based SSH login
-------------------

Dallinger logs in with the private key set as ``server_pem`` and cannot use
passwords. If you log in to the server with a password, create a key on your
computer if you don't have one, copy it to the server, and check that you can
log in without a password:

.. code:: bash

    ssh-keygen
    ssh-copy-id your-username@my-server.example.org
    ssh your-username@my-server.example.org

Then set ``server_pem`` to the private key, for example ``~/.ssh/id_ed25519``.

The account also needs passwordless ``sudo`` the first time the server is
registered, if Docker is not yet installed or the account is not yet in the
``docker`` group.

DNS records
-----------

The server needs a name, and every subdomain of that name must resolve to the
server as well, because each experiment is served at
``https://<app>.<server-name>``. Create two records with your DNS provider:

- ``my-server.example.org``, pointing at the server;
- ``*.my-server.example.org``, pointing at the same place.

Use A records with the server's IP address, or, for an EC2 instance, CNAME
records with the instance's Public IPv4 DNS name
(``ec2-18-170-115-131.eu-west-2.compute.amazonaws.com``). Before each
deployment, Dallinger checks that the experiment's address resolves to the
same IP address as the server, and stops with a ``DNS resolution error`` if it
doesn't.

In Route 53, open **Hosted zones**, select the domain and click **Create
record**. Enter ``my-server`` as the record name, choose the record type and
value, and click **Create records**. Repeat with ``*.my-server``. **View
status** shows when a change has taken effect, usually within a minute. If you
don't have a domain yet, register one from the Route 53 dashboard; this can
take from a few minutes to several hours.

An EC2 instance gets a new Public IPv4 DNS name each time it is stopped and
started. Records you created by hand then point at the old name and must be
updated. ``dallinger ec2 stop`` and ``start`` do this only for servers created
with ``dallinger ec2 provision``.

If the name was used before by another machine, SSH refuses to connect with
``REMOTE HOST IDENTIFICATION HAS CHANGED``; see
:ref:`deploy_troubleshooting_host_key`.

.. lab-note::

   A research group can share one domain, with a subdomain for each
   researcher's server, for example ``alice.<lab-domain>`` with apps at
   ``my-app.alice.<lab-domain>``.

Creating an EC2 instance in the AWS console
-------------------------------------------

1. In the EC2 console, switch to the region closest to your participants
   with the menu in the top-right corner, then open **Instances** and click
   **Launch instances**.
2. Name the instance and choose the Ubuntu image.
3. Choose an x86 instance type, such as ``m7i.large`` for a pilot or
   ``m7i.xlarge`` for a live study (``dallinger ec2 provision`` defaults to
   ``m5.xlarge``). See `EC2 instance types <https://aws.amazon.com/ec2/instance-types/>`_
   and `On-Demand pricing <https://aws.amazon.com/ec2/pricing/on-demand/>`_.
4. Click **Create key pair**, choose RSA, and download the PEM file. Move it
   to ``~/.ssh`` and set it as ``server_pem`` as described in
   :doc:`/deploy/setting_up_a_server`.
5. Click **Create security group** and allow SSH, HTTP and HTTPS traffic. If
   your IP address is fixed, you can restrict SSH to it; you then have to
   update the rule whenever your address changes.
6. Set the storage to at least 32 GB, the ``dallinger ec2 provision``
   default, and click **Launch instance**.
7. Wait until the **Status check** column no longer says *Initializing*, then
   select the instance and copy its **Public IPv4 DNS**. Check that you can log
   in as ``ubuntu``, the default user on AWS Ubuntu images:

   .. code:: bash

       ssh -i ~/.ssh/test-psynet.pem ubuntu@ec2-18-170-115-131.eu-west-2.compute.amazonaws.com

   Accept the host key when SSH asks. If the command hangs without output,
   check that the security group allows SSH from your IP address.

Then create the DNS records and register the server with ``--user ubuntu``.
The instance costs money until you terminate it in the console; stopping it
pauses the compute charge but not the storage charge.

Physical servers
----------------

A physical server avoids ongoing cloud costs and keeps the hardware and data
under your control. In exchange, someone has to maintain it on site, including
restarting it after power cuts, and the network setup has to be agreed with
your institution's IT department.

Hardware
^^^^^^^^

These recommendations date from late 2024:

- a modern multi-core CPU, such as a 16-core AMD Ryzen, to run several
  experiments at once;
- at least 32 GB of RAM;
- one SSD (for example 1 TB NVMe) for the operating system and experiment
  code, and a second SSD (for example 4 TB) for databases and data;
- no dedicated GPU.

Manuel Anglada-Tort compiled these recommendations.

Software
^^^^^^^^

Install Ubuntu 22.04 LTS or 24.04 LTS. Nothing else needs installing by hand:
registration installs Docker if it is missing, and PostgreSQL, Redis and the
web server run in Docker containers.

Network
^^^^^^^

- Ports 80 and 443 must accept incoming traffic from anywhere. The server's
  web server, Caddy, listens on both, serves experiments over HTTPS and
  obtains their certificates from Let's Encrypt, so no manual certificate
  setup is needed.
- SSH (port 22) only needs to be reachable from the computers you deploy
  from. Restricting it to an internal network or a VPN is safer; connect to
  the VPN before each deployment command.
- If the institution's firewall doesn't allow direct incoming traffic on
  ports 80 and 443, ask IT whether an institutional reverse proxy can forward
  it to the server.

Using the server from another computer
--------------------------------------

To deploy to an existing server from another computer, copy the server's
private key to ``~/.ssh`` on that computer, run ``chmod 600`` on it and set
``server_pem`` to it. If SSH is restricted to certain IP addresses, check that
the computer uses one of them. Then log in once with ``ssh`` to check the
connection, and register the server with ``dallinger docker-ssh servers add``.
