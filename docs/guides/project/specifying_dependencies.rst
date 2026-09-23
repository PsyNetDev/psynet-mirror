=======================
Specifying dependencies
=======================

The Python packages required by a given PsyNet experiment should be specified
in requirements.txt. If you are just using PsyNet, then you would normally just
have PsyNet in requirements.txt. However, if you want to use additional packages
(e.g. librosa) then you should add them underneath.

PsyNet as a dependency
----------------------

Because PsyNet is currently released via GitLab, its requirements string looks somewhat
different to other Python packages. It looks like this:

.. code-block:: text

  psynet@git+https://gitlab.com/PsyNetDev/PsyNet#egg=psynet

It is usually a good idea to specify a particular version of PsyNet here so that
your experiment doesn't break when later versions of PsyNet are released.
You can do this by adding `@<tag>` after the repository link, for example:

.. code-block:: text

  psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.0.0#egg=psynet

to specify PsyNet 10.0.0. You can also use a Git commit hash instead of a tag
if you want to link to a particular commit, or indeed a particular Git branch name.

Depending on your mode of deployment, you may be asked to generate a `constraints.txt`
file before deploying. This specifies the precise versions of all packages that would
be installed as dependencies for your experiment. You can create this file
by running ``psynet generate-constraints`` when prompted.

Custom package dependencies
---------------------------

When using a custom package in a Dallinger/PsyNet experiment, you also need to include it in your experiment’s ``requirements.txt``. You can use a package by including the following in your requirements:

.. code-block:: text

  <package_name>@git+<link_to_repository>@<commit_hash_or_branch_name>#egg=<package_name>

For example,

.. code-block:: text

  <package_name>@git+https://gitlab.com/computational-audition-lab/theory-rep-samp/vowels@v1.5.1#egg=vowel_extract

If the repository is a private repository, you will need to generate a custom deploy token. Follow the process described in :ref:`Deploy tokens` and based on the above example replace ``username`` and ``deploy_token`` in the line below accordingly.

.. code-block:: text

  <package_name>@git+https://<username>:<deploy_token>@gitlab.com/computational-audition-lab/theory-rep-samp/vowels@v1.5.1#egg=vowel_extract


Other dependencies
------------------

It is also possible to to specify software dependencies that are not Python packages
but are instead command-line utilities, for example ``sox`` or ``ffmpeg``.
This is is easily done if you use the Docker mode for deployment,
as is the default for SSH deployment to custom servers.

This is achieved by adding a custom text file to your experiment directory
entitled ``prepare_docker_image.sh``. This should be a shell script that installs
any additional software that you need onto your Docker image. You can assume that this
command will be run on a Linux image. For an example, see the
:ref:`Consonance and the carillon <consonance_carillon>` experiment, which includes a
custom ``prepare_docker_image.sh`` script for installing the ``libsndfile1`` utility.

