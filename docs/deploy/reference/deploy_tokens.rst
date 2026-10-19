.. _Deploy tokens:

Deploy tokens
-------------

A deployed experiment installs its packages from ``requirements.txt`` when the
Docker image is built. If one of them lives in a private GitLab repository, the
server needs a deploy token to download it. The token goes into the package's
URL (see :doc:`/code/project/dependencies`).

To create a deploy token:

#.
  Go to the package repository in GitLab.

#.
  Go to ``Settings/Repository/Deploy Tokens`` and click ``Expand``.

#.
  Set the ``name`` & ``username`` to however you want to refer to it, for example 'vowel' for both. (You don’t have to set the username; if you don’t, one will be assigned.)

#.
  Set the ``expiration date``.  Set it to a date equal or greater than today plus the length of time you will be running experiments, e.g. a date in a few months.

#.
  Enable ``read_repository``, ``read_registry``, and ``read_package_registry``. You don’t have to enable the others.

#.
  Press ``Create Deploy Token``. It will show you the ``name``, ``username``, and ``deploy token``. Make sure this token is saved somewhere safe; it will only be shown to you once when you create it.

The general scheme for authenticating using a deploy token is ``username:deploy_token``.
The token is stored in ``requirements.txt`` and in the Docker image, so anyone
who can read either can download the package.

.. lab-note::

   Your lab may already have deploy tokens for its shared private packages.
   Ask your lab administrator before creating a new one.
