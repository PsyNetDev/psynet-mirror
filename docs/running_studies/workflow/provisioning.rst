Provisioning
============

Servers
-------

PsyNet experiments are deployed to an SSH-accessible Linux server. You
can use several types of server depending on your setup:

- **Your own physical server**: install Ubuntu and expose it to the
  internet. See the :doc:`physical server setup guide
  </running_studies/reference/physical_server_setup>`.
- **A cloud provider (e.g., AWS EC2, Hetzner, Contabo)**: rent a virtual
  machine with SSH access. See the :ref:`SSH server guide <ssh_server>`
  and :ref:`AWS server setup guide <aws_server_setup>`.
- **A lab-provided internal server**: if your lab has a shared server,
  follow your lab's instructions for adding it to Dallinger.

Once you have a server, register it with Dallinger once:

.. code:: bash

   dallinger docker-ssh servers add --host <your-server-hostname> --user <your-username>

For the full list of server options and trade-offs, see the
:doc:`web servers overview </running_studies/reference/web_servers>`.

EC2 servers
-----------

If your lab uses AWS EC2, PsyNet can provision and tear down servers for
you automatically. Before using it, make sure AWS credentials, SSH
access, DNS, and the Docker registry are configured as described in the
:ref:`AWS server setup <aws_server_setup>` and :ref:`SSH server
<ssh_server>` guides. For the full command reference, including
choosing a region, provisioning, stopping/starting, and troubleshooting,
see :doc:`AWS automatic provisioning </running_studies/reference/aws_automatic_provisioning>`.

In your lab's day-to-day workflow, the two things worth remembering are:

- Name your server so that others can tell who deployed it, for example
  ``alice-melody-batch2`` rather than ``melody123``. The recommended
  convention is ``name-experiment-version``.
- Choose an instance size for your purpose: something small like
  ``m7i.large`` for debugging, and something larger like ``m7i.xlarge``
  for a live deployment with many simultaneous participants.

.. code:: bash

   dallinger ec2 provision --name alice-melody-batch2 --region us-west-2 --dns-host alice.<your-domain> --type m7i.xlarge
