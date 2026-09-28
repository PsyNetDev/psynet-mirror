.. _aws_server_setup:

========================
Setting up an AWS server
========================

This page describes how to create an EC2 server by hand in the AWS console.
``dallinger ec2 provision`` does the same automatically; see
:doc:`/deploy/setting_up_a_server`. You pay for the server while it is
running; the example instance types below cost roughly $2.5–5 per day (check
the AWS documentation to confirm exact pricing).

Creating the instance
---------------------

1. Sign into your AWS account at https://aws.amazon.com/.

2. Go to the EC2 panel.

3. (Optional) Switch to the region closest to your participants using the
   dropdown in the top-right corner of the page, for example 'eu-west-2'.

4. Click on 'Instances'.

5. Click 'Launch instances'.

6. Give your instance a name, for example 'Test PsyNet server'.

7. Select 'Ubuntu' as the OS image.

8. Choose an appropriate instance type. Different instance types have different costs
   and different performances. The appropriate instance type will depend on your use case.
   You can explore options online at
   https://aws.amazon.com/ec2/instance-types/
   and
   https://aws.amazon.com/ec2/pricing/on-demand/.
   Note that you need an instance with x86 rather than ARM architecture.
   For prototyping, something like ``m7i.large`` might work fine (2 vCPU, 8 GB RAM, c. $2.5/day);
   for running an experiment with multiple simultaneous participants, it might
   be better to go with something larger like ``m7i.xlarge`` (4 vCPU, 16 GB RAM, c. $5/day).
   In order to avoid unnecessary costs, we recommend that you 'stop' or 'terminate' your instance
   when you're not using it. 'Stopping' pauses the instance, but you will still pay a small ongoing fee
   for storage. 'Terminating' completely deletes the instance and associated data, and eliminates your
   ongoing fees.

9. Click 'Create key pair' (RSA) and give it a name, e.g. 'test-psynet'.
   When done, a PEM file is downloaded to your computer.
   Move it to ``~/.ssh``, make it readable only by you, and set it as
   ``server_pem`` in ``~/.dallingerconfig``:

   .. code:: bash

       mv ~/Downloads/test-psynet.pem ~/.ssh/
       chmod 400 ~/.ssh/test-psynet.pem

   .. code:: ini

       [SSH]
       server_pem = ~/.ssh/test-psynet.pem

10. Click 'Create security group'. You have some decisions here about security.
    Tick all boxes (allow SSH, allow HTTPS, allow HTTP).
    If you are confident that you have a fixed IP address, and
    know how to update your AWS settings if it changes, change
    the SSH traffic option to only allow traffic from my IP address.

11. Set storage to 30 GB.

12. Leave all other options at their defaults, and click launch instance.
    Your instance will take a while to boot. You can click on the instances
    tab to see the current status of them. While the 'status check'
    column still says 'initializing', you'll still have to wait longer.

13. Once the instance is ready, select it in the AWS panel,
    and find the Public IPv4 DNS. This is the URL of your instance. It should
    look something like this: ``ec2-18-170-115-131.eu-west-2.compute.amazonaws.com``

14. Verify that you can SSH to this instance by running the following in your terminal,
    replacing the example with your own IPv4 DNS as appropriate:

    .. code:: bash

        ssh -i ~/.ssh/test-psynet.pem ubuntu@ec2-18-170-115-131.eu-west-2.compute.amazonaws.com

    You will probably see a warning message of the form 'The authenticity of host XXX can't be established';
    this is to be accepted. Type yes and press enter.
    If your login doesn't work (especially if it freezes with no output printed to the terminal),
    you may have to examine your security group/IP address combination.

Setting up DNS
--------------

The examples below give the server the name ``my-server.example.org``, with
experiments at subdomains such as ``my-app.my-server.example.org``.

1. If you don't have a domain name yet, register one: in the AWS console,
   open the Route 53 service and register a domain from its dashboard.
   Different domain names come with different costs, and registration can
   take from a few minutes to several hours. Wait until the AWS console tells
   you that the registration is complete.

2. Create a subdomain for the server. Go to the 'Hosted zones' page and
   select your domain name. Click 'Create record' and type ``my-server`` under
   record name. Set the record type to 'CNAME', and set the value to your
   instance's Public IPv4 DNS as copied above (it looks something like
   ``ec2-23-54-234-12.eu-west-2.compute.amazonaws.com``). Click 'Create
   records' to finalize.

   This change can take up to a minute to take effect; click 'View status' to
   confirm that it has. You should then be able to SSH to your server using
   its new name:

   .. code:: bash

       ssh -i ~/.ssh/test-psynet.pem ubuntu@my-server.example.org

3. Create a wildcard subdomain for the apps you deploy. Repeat the previous
   step with ``*.my-server`` as the record name. After a minute or so, test it:

   .. code:: bash

       ssh -i ~/.ssh/test-psynet.pem ubuntu@my-app.my-server.example.org

.. note::

    If you have used this subdomain before with a different (virtual) machine, you may see an error message
    like this:

    .. code:: text

        @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
        @    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
        @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
        IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
        Someone could be eavesdropping on you right now (man-in-the-middle attack)!
        It is also possible that a host key has just been changed.
        The fingerprint for the ED25519 key sent by the remote host is
        SHA256:...
        Please contact your system administrator.
        Add correct host key in /Users/your-username/.ssh/known_hosts to get rid of this message.
        Offending ED25519 key in /Users/your-username/.ssh/known_hosts:11
        Host key for my-server.example.org has changed and you have requested strict checking.
        Host key verification failed.

    To fix this problem, enter the following on your local machine,
    replacing the server name as appropriate:

    .. code:: bash

        ssh-keygen -R my-server.example.org

.. lab-note::

   A research group can share one domain, with a subdomain for each
   researcher's server, for example ``alice.<lab-domain>`` with apps at
   ``my-app.alice.<lab-domain>``.

Registering the server
----------------------

Register the server under its DNS name, with ``ubuntu`` (the default user
on AWS Ubuntu instances) as the user:

.. code:: bash

    dallinger docker-ssh servers add --host my-server.example.org --user ubuntu

The other settings needed before deploying are in
:doc:`/deploy/setting_up_a_server`. Stop or terminate the instance in the
AWS console when you no longer need it.

Using the server from another computer
--------------------------------------

To deploy to an existing server from another computer, copy the PEM file
from the person who set up the server to ``~/.ssh`` on that computer, run
``chmod 400`` on it and set ``server_pem`` to it. If the security group only
allows SSH from a fixed IP address, check that the computer has that
address. Then test the connection with ``ssh`` and register the server with
``dallinger docker-ssh servers add`` as above.
