.. _Deploy tokens:

Deploy tokens
-------------

There already exists a deploy token in GitLab which allows you to deploy your `PsyNet` experiment. But if you want to use a custom package in a deployed/sandboxed experiment, you will need to create a new deploy token.

The steps are as follows:

#.
  Go to the package repository in GitLab.

#.
  Go to ``Settings/Repository/Deploy Tokens`` and click ``Expand``.

#.
  Set the ``name`` & ``username`` to however you want to refer to it. In the above examples, they were both set to 'vowel'. (You don’t have to set the username; if you don’t, one will be assigned.)

#.
  Set the ``expiration date``.  Set it to a date equal or greater than today plus the length of time you will be running experiments, e.g. a date in a few months.

#.
  Enable ``read_repository``, ``read_registry``, and ``read_package_registry``. You don’t have to enable the others.

#.
  Press ``Create Deploy Token``. It will show you the ``name``, ``username``, and ``deploy token``. Make sure this token is saved somewhere safe; it will only be shown to you once when you create it.

The general scheme for authenticating using a deploy token is ``username:deploy_token``.
