Deployment reference
====================

This section is the reference for deployment targets, server setup,
monitoring tools, and troubleshooting. Data export is covered in
:doc:`/data/index`. If you are looking for a
step-by-step lab workflow around these pieces, including recruiter
setup, piloting, monitoring participants, and teardown, see the
:doc:`Lab research workflow </deploy/workflow/index>`.

.. warning::

   ``deploy.toml`` planning currently requires a POSIX filesystem and is not
   supported on Windows.

.. toctree::
   :maxdepth: 1

   web_servers
   aws_automatic_provisioning
   aws_server_setup
   physical_server_setup
   ssh_server
   deploy_from_archive
   deploy_tokens
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
