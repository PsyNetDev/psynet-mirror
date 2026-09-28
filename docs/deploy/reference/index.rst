Deployment reference
====================

.. warning::

   ``deploy.toml`` planning currently requires a POSIX filesystem and is not
   supported on Windows.

.. toctree::
   :maxdepth: 1

   ssh_server
   aws_automatic_provisioning
   aws_server_setup
   physical_server_setup
   deploy_tokens
   ad_page
   deploy_from_archive
   deployment_monitor
   setting_up_slack
   errors
   troubleshooting

.. _deployment_build_context:

Deployment build context
------------------------

PsyNet and Dallinger build the Docker context from the experiment's
``deploy.toml`` policy. This keeps debug staging and deployment backends on the
same reviewed file plan; ``.gitignore`` only controls Git. PsyNet creates
``deploy.toml`` from its template when the file is missing. See Dallinger's
`deploy.toml guide <https://github.com/Dallinger/Dallinger/blob/master/docs/source/deploy_toml.rst>`_
for the file format and ``dallinger deployment-files list``.

Use ``psynet debug local --docker`` or a Docker deploy command so that the reviewed
plan controls the image context. Direct ``docker build`` in the experiment
directory does not read ``deploy.toml`` and can send local files such as
``.env`` and ``.venv`` to the Docker daemon.
