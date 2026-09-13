Running PsyNet remotely
=======================

PsyNet experiments are typically deployed to a remote server.
You can use your own pre-existing server,
or you can use Dallinger (one of PsyNet's dependencies) to provision a server for you from Amazon Web Services (AWS).
We will describe both approaches below.

Before you start, you will likely need to create a ``.dallingerconfig`` file in your local machine's home directory.

.. code-block:: bash

    touch ~/.dallingerconfig

This ``.dallingerconfig`` file provides global configuration options for PsyNet and Dallinger
(see :doc:`../experiment_development/configuration` for more details).

Setting up the server
---------------------

Use the tabs below to switch between the different ways of setting up a remote server:

.. tab:: Using your own server

    Suppose you already have a server, and it has a domain name which resolves to its IP address
    (e.g. ``my-server.com``). This server must not be configured to rely on a password to authenticate,
    it should instead use a key pair (i.e. a public key, which sits on the server, and a private key,
    which sits on your local machine).
    The private key might be your personal private key (typically ``~/.ssh/id_rsa`` or ``~/.ssh/id_ed25519``)
    or alternatively it might be a PEM file that you received when setting up the server.
    If it's a PEM file, you should copy it to the ``~/.ssh`` directory (e.g. ``~/.ssh/my-server.pem``).

    Before continuing, you should test that you can connect to your server using SSH.
    If you are using a personal private key, you should be able to connect as follows
    (we will suppose that the server's domain name is ``my-server.com`` and the username is ``ubuntu``):

    .. code-block:: bash

        ssh ubuntu@my-server.com

    If you are using a PEM file, you will need to pass it to the SSH client:

    .. code-block:: bash

        ssh -i ~/.ssh/my-server.pem ubuntu@my-server.com

    Once you've verified that you can connect to your server using SSH,
    close the connection using ``Ctrl+C``.
    You then need to tell Dallinger about your private key by adding the following to ``~/.dallingerconfig``,
    setting the ``server_pem`` option to the path of your private key:

    .. code-block:: bash

        [PEM files]
        server_pem = ~/.ssh/id_rsa  # or ~/.ssh/id_ed25519, or ~/.ssh/my-server.pem, as appropriate

    You can then register your server from your terminal:

    .. code-block:: bash

        dallinger docker-ssh servers add --host my-server.com --user ubuntu

    This might take a few minutes as Dallinger will install any required dependencies.
    Don't worry if you see an error message about Docker not being found;
    Dallinger will install Docker for you.

.. tab:: Provisioning an AWS server

    Renting an AWS server costs money if you do it for a long time. However, the average
    PsyNet experiment only takes a few hours to run (because participants are quick to recruit with Prolific),
    so AWS costs only need to be a few dollars. However, if you forget to stop the server when you're done,
    you might incur much larger costs. **You must therefore be very careful when using AWS servers,
    and double-check your AWS console to ensure that you are not incurring unexpected costs.**

    .. note::

        At the time of writing (January 2026), the recommended AWS server type for deployment
        is ``m7i.xlarge`` (16 GB RAM, 4 vCPUs), which costs around $0.20 an hour.
        A five-hour experiment should therefore only cost around $1.

    If you like, you can provision an AWS server yourself using the AWS console.
    If you do it this way, you can register it like any other server via the 'Using your own server' method.
    Alternatively, you can get Dallinger to provision the AWS server for you following the steps below.

    .. warning::

        The instructions below involve sharing your AWS credentials with Dallinger.
        AWS credentials are sensitive information; if someone else gets hold of them,
        they could use them to access your AWS account and incur unexpected costs.
        There is a minor possibility that this could happen one day if one of PsyNet's dependencies
        ended up being compromised by a bad actor. To protect yourself from this, we recommend
        using Identity and Access Management (IAM) to minimise the scope of your credentials.
        We also recommend deleting your credentials after use (you can do this in the AWS console).

    If you use IAM to manage your credentials (recommended), you will need to create your IAM user
    with the following permissions:

    .. code-block:: bash

        AmazonEC2FullAccess
        AmazonRoute53FullAccess
        AmazonS3FullAccess  # only if you want to use S3 for storing experiment data/backups

    If you are working within a research group using PsyNet, ask your lab manager to create these credentials for you.

    Once you have your AWS credentials, you will need to place them in the ``~/.dallingerconfig`` file
    mentioned above.

    .. code-block:: bash

        [AWS]
        aws_access_key_id = your-secret-aws-access-key-id
        aws_secret_access_key = your-secret-aws-secret-access-key

    You'll also need to register a domain name in AWS Route 53.
    We recommend that research groups register a single shared domain for the entire group
    (e.g. ``cool-psychology.org``).
    Dallinger then makes it easy to use subdomains for each individual server
    (e.g. ``memory-experiments.cool-psychology.org``).

    Lastly, you'll also need to create a key pair for authenticating to the remote servers.
    A research group can share a single key pair if needed.
    The key pair can be created via the AWS console; AWS keeps the public key, and you download the private key
    as a PEM file (e.g. ``cool-psychology.pem``).
    You need to copy your PEM file to the ``~/.ssh`` directory on your local machine
    You then need to put the name of this PEM file in your ``~/.dallingerconfig`` file
    (just the name, not the full path, not the extension).

    .. code-block:: bash

        [PEM files]
        ec2_default_pem = cool-psychology

    You should now be able to provision a server from AWS within your terminal:

    .. code-block:: bash

        dallinger ec2 provision \
            --name memory-experiments \
            --region us-east-1 \
            --dns-host memory-experiments.cool-psychology.org \
            --type m7i.xlarge

    Choose a region close to the location of your participants
    see the `AWS documentation <https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html>`_
    for a list of available regions.

    Your server will then automatically be registered with Dallinger
    (no need to run ``dallinger docker-ssh servers add``).

Running the experiment
----------------------

Once your server is set up, you should be able to deploy the experiment to this server
by running the following command:

.. code-block:: bash

    psynet debug ssh --app your-experiment-name

Your experiment should be ready within a minute or two
at the URL ``https://<your-experiment-name>.<your-dns-host>``.
Note that you can have multiple experiments running on the same server,
as long as they have different app names.

.. note::

    If you encounter an error on deployment, try the following:

    1. Verify that your local environment is up to date by running the following in your terminal:

    .. code-block:: bash

        uv pip install -r constraints.txt

    2. Run ``psynet debug local`` to verify that the experiment runs locally.

    3. Check the server logs by running the following in your terminal:

    .. code-block:: bash

        ssh -i ~/.ssh/your-server.pem your-username@your-server.com
        cd ~/dallinger/your-experiment-name
        docker compose logs

If you want to share your experiment with others, look in your console logs for a
'Single recruitment link'. This link can be used to participate in the experiment.

Cleaning up
-----------

Once you are done with your experiment, you can remove it from the server by running the following:

.. code-block:: bash

    psynet destroy ssh --app your-experiment-name

If you created your server using AWS, you may wish to delete it too:

.. code-block:: bash

    dallinger ec2 teardown --name memory-experiments --region us-east-1
